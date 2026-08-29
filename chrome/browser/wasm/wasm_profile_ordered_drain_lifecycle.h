// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CHROME_BROWSER_WASM_WASM_PROFILE_ORDERED_DRAIN_LIFECYCLE_H_
#define CHROME_BROWSER_WASM_WASM_PROFILE_ORDERED_DRAIN_LIFECYCLE_H_

#include <cstdint>
#include <optional>

#include "base/memory/ref_counted.h"
#include "base/memory/scoped_refptr.h"
#include "base/synchronization/lock.h"

// Coordinates the application-side admission ordering required before the
// outer ChromeMain path may make one irreversible WasmFS/OPFS handoff attempt:
//
//   1. close explicit profile-I/O admission;
//   2. await every already admitted operation;
//   3. reject a clean handoff if any operation in this epoch failed or was
//      abandoned, including one that finished before admission closed; and
//   4. issue either one move-only clean-drain permit or one distinct terminal
//      failure-retirement permit for the outer, post-ContentMain seam.
//
// This type deliberately does not invoke or acknowledge the backend
// transaction. The narrowly source-selected M7 test storage adapter accepts
// its permit only after ContentMain and its delegate scope have returned, then
// invokes the one concrete WasmFS transaction that seals the backend, accounts
// for every target descriptor, flushes and closes data files, conditionally
// releases the lease, and retires the worker. Keeping that call outside this
// epoch prevents an early release while profile teardown can still issue I/O.
//
// This remains a narrow control-plane primitive. Its M7 test adapter registers
// only known Preferences and SQLite/LevelDB smoke operations; it does not make
// all Chrome profile I/O use admission handles and it does not establish full
// profile persistence, durability, recovery, or lock semantics. A clean result
// means only that its explicitly admitted epoch is ready to be handed to the
// outer drain seam; it is never a storage success claim. A non-clean result can
// authorize only terminal backend retirement, never a clean profile handoff.
class WasmProfileOrderedDrainLifecycle {
 public:
  enum class ProfileIOCompletion {
    kSucceeded,
    kFailed,
  };

  enum class ProfileIOQuiesceStatus {
    kWaiting,
    kAllRegisteredOperationsSucceeded,
    kRegisteredOperationFailed,
    kRegisteredOperationAbandoned,
  };

  // Counts every operation admitted during this lifecycle epoch. The outcome
  // counters are intentionally lifetime-wide rather than scoped only to holds
  // that remained outstanding when BeginQuiesce() closed admission.
  struct ProfileIOQuiesceResult {
    ProfileIOQuiesceStatus status = ProfileIOQuiesceStatus::kWaiting;
    uint64_t admitted_operations = 0;
    uint64_t outstanding_at_begin = 0;
    uint64_t succeeded_operations = 0;
    uint64_t failed_operations = 0;
    uint64_t abandoned_operations = 0;

    bool Succeeded() const {
      return status ==
             ProfileIOQuiesceStatus::kAllRegisteredOperationsSucceeded;
    }
  };

  // The durable state of the explicitly registered-I/O epoch.
  // kReadyForPostContentDrain is the only state from which a permit can be
  // claimed. A retired permit means it is no longer held, but establishes
  // nothing about a backend attempt. This preparatory type has no
  // consumed/success state because only the future outer storage adapter can
  // truthfully report a backend result.
  enum class Status {
    kAcceptingRegisteredProfileIO,
    kWaitingForRegisteredProfileIO,
    kReadyForPostContentDrain,
    kRegisteredProfileIONotClean,
    kAbortedBeforePostContentDrain,
    kPostContentDrainPermitClaimed,
    kPostContentDrainPermitRetired,
    kPostContentFailureRetirementPermitClaimed,
    kPostContentFailureRetirementPermitRetired,
  };

  struct Result {
    Status status = Status::kAcceptingRegisteredProfileIO;
    ProfileIOQuiesceResult profile_io;

    bool ReadyForPostContentDrain() const {
      return status == Status::kReadyForPostContentDrain &&
             profile_io.Succeeded();
    }
  };

  class Observation;

  // A move-only explicit admission. It is safe to complete or destroy from
  // any sequence. Destruction records an abandoned operation, which poisons
  // this lifecycle epoch even if it happens before BeginQuiesce().
  class ProfileIOHold {
   public:
    ProfileIOHold(ProfileIOHold&& other) noexcept;
    ProfileIOHold& operator=(ProfileIOHold&& other) noexcept;
    ~ProfileIOHold();

    ProfileIOHold(const ProfileIOHold&) = delete;
    ProfileIOHold& operator=(const ProfileIOHold&) = delete;

    // Records the operation's final outcome and releases the admission.
    // Returns false for an already completed or moved-from handle.
    bool Complete(ProfileIOCompletion completion);

   private:
    friend class Observation;

    explicit ProfileIOHold(scoped_refptr<Observation> observation);
    void Reset();

    scoped_refptr<Observation> observation_;
  };

  // A one-shot proof that the explicitly admitted profile-I/O epoch completed
  // cleanly. It exposes only a fixed registered-I/O snapshot; this
  // preparatory type deliberately has no public operation that can claim a
  // backend drain began. A future ChromeMain-owned storage adapter must accept
  // the permit only after ContentMain returns and immediately before the
  // concrete backend drain. Destroying the permit retires it and permanently
  // refuses another permit. Retirement deliberately does not distinguish a
  // lost handoff from a future adapter that has returned from the raw drain;
  // neither case can be mistaken for a clean release without the concrete
  // storage result.
  class PostContentDrainPermit {
   public:
    PostContentDrainPermit(PostContentDrainPermit&& other) noexcept;
    PostContentDrainPermit& operator=(PostContentDrainPermit&& other) noexcept;
    ~PostContentDrainPermit();

    PostContentDrainPermit(const PostContentDrainPermit&) = delete;
    PostContentDrainPermit& operator=(const PostContentDrainPermit&) = delete;

    // Returns a fixed copy of the clean registered-I/O result. It never
    // acknowledges, invokes, or reports the later storage drain. A moved-from
    // permit returns nullopt.
    std::optional<ProfileIOQuiesceResult> GetProfileIOQuiesceResult() const;

   private:
    friend class Observation;

    PostContentDrainPermit(scoped_refptr<Observation> observation,
                            ProfileIOQuiesceResult profile_io);
    void Reset();

    scoped_refptr<Observation> observation_;
    ProfileIOQuiesceResult profile_io_;
  };

  // A move-only proof that every registered profile operation has reached a
  // terminal non-clean outcome. It permits the outer storage adapter to seal
  // and perform fail-closed backend teardown after ContentMain returns,
  // preventing raw WasmFS destruction from owning live OPFS file handles. It
  // never authorizes a clean persistence result: the adapter must preserve the
  // registered-I/O failure in its returned storage result even if physical
  // teardown works.
  class PostContentFailureRetirementPermit {
   public:
    PostContentFailureRetirementPermit(
        PostContentFailureRetirementPermit&& other) noexcept;
    PostContentFailureRetirementPermit& operator=(
        PostContentFailureRetirementPermit&& other) noexcept;
    ~PostContentFailureRetirementPermit();

    PostContentFailureRetirementPermit(
        const PostContentFailureRetirementPermit&) = delete;
    PostContentFailureRetirementPermit& operator=(
        const PostContentFailureRetirementPermit&) = delete;

    // Returns the fixed non-clean registered-I/O result. A moved-from permit
    // returns nullopt.
    std::optional<ProfileIOQuiesceResult> GetProfileIOQuiesceResult() const;

   private:
    friend class Observation;

    PostContentFailureRetirementPermit(
        scoped_refptr<Observation> observation,
        ProfileIOQuiesceResult profile_io);
    void Reset();

    scoped_refptr<Observation> observation_;
    ProfileIOQuiesceResult profile_io_;
  };

  // A thread-safe, ref-counted epoch that the outer ChromeMain path retains
  // across ContentMain/delegate destruction. It contains no task runner or
  // callback, so a discarded shutdown task cannot strand the state or destroy
  // an owner-affine observer on a worker sequence.
  class Observation : public base::RefCountedThreadSafe<Observation> {
   public:
    Result GetResult() const;

    // Claims the one permit only after registered I/O has quiesced cleanly.
    // It does not invoke or report the backend drain itself.
    std::optional<PostContentDrainPermit> ClaimPostContentDrain();

    // Claims the one terminal-retirement permit only after registered I/O has
    // quiesced with a failed or abandoned operation. It does not turn that
    // failure into a clean handoff and does not invoke the backend itself.
    std::optional<PostContentFailureRetirementPermit>
    ClaimPostContentFailureRetirement();

   private:
    friend class base::RefCountedThreadSafe<Observation>;
    friend class WasmProfileOrderedDrainLifecycle;
    friend class ProfileIOHold;
    friend class PostContentDrainPermit;
    friend class PostContentFailureRetirementPermit;

    enum class ProfileIOHoldDisposition {
      kSucceeded,
      kFailed,
      kAbandoned,
    };

    static scoped_refptr<Observation> Create();
    Observation();
    ~Observation();

    std::optional<ProfileIOHold> TryAcquireProfileIO();
    bool BeginQuiesce();
    bool AbortBeforePostContentDrain();
    void ReleaseProfileIOHold(ProfileIOHoldDisposition disposition);
    void RetirePostContentDrainPermit();
    void RetirePostContentFailureRetirementPermit();

    void UpdateQuiesceStatusLocked() EXCLUSIVE_LOCKS_REQUIRED(lock_);
    ProfileIOQuiesceResult BuildProfileIOQuiesceResultLocked() const
        EXCLUSIVE_LOCKS_REQUIRED(lock_);

    mutable base::Lock lock_;
    Status status_ GUARDED_BY(lock_) = Status::kAcceptingRegisteredProfileIO;
    uint64_t admitted_operations_ GUARDED_BY(lock_) = 0;
    uint64_t active_holds_ GUARDED_BY(lock_) = 0;
    uint64_t outstanding_at_begin_ GUARDED_BY(lock_) = 0;
    uint64_t succeeded_operations_ GUARDED_BY(lock_) = 0;
    uint64_t failed_operations_ GUARDED_BY(lock_) = 0;
    uint64_t abandoned_operations_ GUARDED_BY(lock_) = 0;
  };

  WasmProfileOrderedDrainLifecycle();
  WasmProfileOrderedDrainLifecycle(const WasmProfileOrderedDrainLifecycle&) =
      delete;
  WasmProfileOrderedDrainLifecycle& operator=(
      const WasmProfileOrderedDrainLifecycle&) = delete;
  ~WasmProfileOrderedDrainLifecycle();

  // Acquires admission for one registered profile operation while admissions
  // remain open. An operation that is denied cannot be omitted from a later
  // drain result because it was never permitted to start.
  std::optional<ProfileIOHold> TryAcquireProfileIO();

  // Atomically closes admission and returns a durable observation for the
  // outer ChromeMain path. It returns nullptr for a duplicate or aborted
  // request. Once all already admitted operations reach a terminal outcome,
  // Observation::GetResult() becomes either kReadyForPostContentDrain or
  // kRegisteredProfileIONotClean.
  scoped_refptr<Observation> BeginQuiesce();

  // Permanently rejects new admissions and prevents a clean outer handoff.
  // It is allowed only before a permit is claimed. Existing holds still record
  // their outcomes through any retained Observation.
  bool AbortBeforePostContentDrain();

 private:
  const scoped_refptr<Observation> observation_;
};

#endif  // CHROME_BROWSER_WASM_WASM_PROFILE_ORDERED_DRAIN_LIFECYCLE_H_

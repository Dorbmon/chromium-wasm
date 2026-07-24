# Chromium Wasm product porting ledger

This is the versioned product ledger. It groups work by root cause rather than
compiler-error order. The machine-readable
[`tools/wasm/m1_inventory.json`](../../tools/wasm/m1_inventory.json) is the
historical M1.0 pre-implementation snapshot; the statuses below are the final
M1 assessment.

Status meanings:

- **Verified** — implemented and exercised by the M1 Node and browser gates.
- **Verified boundary** — the supported subset works and unsupported behavior
  fails explicitly.
- **Explicit unsupported** — intentionally unavailable in the WebAssembly
  architecture and tested not to report false success.
- **Deferred** — not required by the focused M1 acceptance gate and still
  requires implementation or inventory before its first consumer.

## Build and source selection

| ID | Target | Implemented boundary | Status |
|---|---|---|---|
| BUILD-001 | M1 smoke graph | The opt-in root `gn_all` contains the M0 executable and every M1 positive and negative executable | Verified |
| BUILD-002 | focused Base subset | `base/BUILD.gn` permits only the explicit Chromium Wasm port and exposes narrow M1 source sets | Verified |
| BUILD-003 | platform sources | Dedicated Wasm source selection; Wasm remains neither Linux nor broadly POSIX | Verified |

## Base platform ABI and primitives

| ID | Capability | Implemented boundary | Status |
|---|---|---|---|
| BASE-ABI-001 | thread types | Emscripten pthread handle plus stable Wasm thread ID | Verified |
| BASE-ABI-002 | lock/CV types | Wasm pthread storage and explicitly selected implementations | Verified |
| BASE-ABI-003 | VFS descriptor types | Emscripten MEMFS descriptors are confined to Wasm file implementations | Verified boundary |
| BASE-ABI-004 | path/stat types | Narrow paths and MEMFS metadata without global POSIX classification | Verified |
| BASE-ABI-005 | process identity | One stable module-local identity; no child-process handles | Verified boundary |
| BASE-TIME-001/2/4 | wall, monotonic, and high-resolution behavior | `time_wasm.cc` uses the Emscripten wall and monotonic runtime clocks | Verified |
| BASE-TIME-003 | per-thread CPU time | `ThreadTicks::IsSupported()` remains false | Explicit unsupported |
| BASE-RAND-001/2 | secure entropy | `getentropy` backed by host cryptographic randomness, including application and worker threads | Verified |
| BASE-THREAD-001 | thread operations | Create, join, yield, and sleep through Emscripten pthreads | Verified |
| BASE-THREAD-002 | thread ID/name | Stable IDs; names are best-effort diagnostic metadata only | Verified boundary |
| BASE-TLS-001 | TLS | Pthread TLS with cross-thread isolation and destructor coverage | Verified |
| BASE-SYNC-001/2 | lock, CV, event | Lock, timed/broadcast CV, manual/auto-reset event, and wait-many behavior | Verified |
| BASE-PATH-001 | platform paths | Current, temporary, and placeholder home paths exist in the VFS; executable/module paths reject | Verified boundary |
| BASE-FILE-001/2 | file I/O and enumeration | MEMFS CRUD, binary I/O, seek, append, truncate, flush, rename, metadata, errors, directories, and enumeration | Verified |
| BASE-PROCESS-001 | identity | Current-process handles and stable process-local ID | Verified |
| BASE-PROCESS-002 | launch/control/output | Launch, non-current open/control, and output capture return invalid/false | Explicit unsupported |
| BASE-SYS-001 | system information | Runtime processor count, 64 KiB page/granularity, wasm32 identity, current/max heap, and runtime-relative uptime | Verified boundary |
| BASE-ENV-001 | `base::Environment` | No focused Wasm implementation or behavior test yet | Deferred |
| BASE-CMD-001 | command-line handling | Generic parsing is linked where needed, but has no dedicated M1 behavior gate | Deferred |
| BASE-STACK-001 | stack diagnostics | Raw Wasm frames appear in abort diagnostics; symbolized Base stack traces are not implemented | Deferred |
| BASE-DYNLIB-001 | dynamic libraries/executable memory | No static registry or executable-memory semantics | Explicit unsupported |

## Base task runtime

| ID | Capability | Implemented boundary | Status |
|---|---|---|---|
| TASK-001 | default message pump | The pinned `MessagePumpDefault` blocks on Wasm `WaitableEvent`, wakes cross-thread, schedules delays, nests, and quits without polling | Verified |
| TASK-002 | task executor | `SingleThreadTaskExecutor` and SequenceManager run on the application pthread while browser timers and animation frames advance | Verified |
| TASK-003 | native UI/I/O pumps | Native window-system and descriptor-loop pump types reject instead of aliasing the generic pump | Explicit unsupported |

The older roadmap proposed a class named `MessagePumpWasm`. The milestone
assignment required evaluating the generic pump first, and its complete
behavioral gate passed. M1 therefore retains the generic implementation instead
of adding a naming-only platform class.

## Rust

| ID | Capability | Implemented boundary | Status |
|---|---|---|---|
| RUST-TOOLCHAIN-001 | compiler install | Exact Chromium Rust archive is downloaded, hashed, extracted atomically, and identity-checked | Verified |
| RUST-TOOLCHAIN-002 | target stdlib | 23 target rlibs are built from the archive's pinned `rustc-src` into the local GN output sysroot | Verified |
| RUST-TOOLCHAIN-003 | pthread codegen | Rust and C++ share Wasm atomics, bulk-memory, mutable-globals, and pthread settings | Verified |
| RUST-GN-001/2/3 | GN target mapping | Conditional Rust enablement, `wasm32-unknown-emscripten`, and wasm32 architecture mapping | Verified |
| RUST-LINK-001 | final link | Rust rlibs enter the pinned Emscripten `em++` final link with cross-toolchain bitcode/ThinLTO disabled | Verified |
| RUST-PANIC-001 | panic behavior | `panic=abort`; isolated runner requires the exact panic marker and abort/nonzero evidence | Verified |
| RUST-ALLOC-001 | allocation/std | `Vec`, `String`, boxed allocation/drop, `Arc`, and `Mutex` execute in the final module | Verified |
| RUST-PRELUDE-001 | Chromium prelude | `build_with_chromium=false` leaves the first-party prelude disabled in this focused graph | Deferred |
| RUST-INTEROP-001 | C++/Rust calls | Chromium `rust_static_library` and pinned CXX bridge in both directions | Verified |
| RUST-THREAD-001 | Rust pthread | `std::thread::spawn`, join, atomics, `Arc`, and `Mutex` pass with browser heartbeat | Verified |
| RUST-TEST-001 | unit-test runner | Dedicated GN-built Node/browser smoke executables are used; native Rust test-runner integration is not ported | Deferred |
| RUST-INVENTORY-001 | Content/Chrome crate closure | Content and Chrome graphs are prohibited before M2/M3 and were not loaded for M1 | Deferred |

The Content/Chrome Rust crate inventory must be performed at the first
standalone V8/Content graph preflight, before disabling any optional consumer.

## Shared memory and Mojo

| ID | Capability | Implemented boundary | Status |
|---|---|---|---|
| SHMEM-001 | handle type | Opaque region ID, generation, rights, size, and GUID metadata; no Unix descriptor | Verified |
| SHMEM-002 | storage/duplication | Locked process-local aligned registry with move-only writable and duplicable read-only/unsafe capabilities | Verified |
| SHMEM-003 | mapping lifetime | Independent mapping references, duplicate-address accounting, stale/range rejection, and mapping-after-handle lifetime | Verified |
| SHMEM-004 | read-only mode | Rights are enforced at typed API/capability boundaries, without hardware page protection | Verified boundary |
| MOJO-001 | core selection | Pinned ipcz core with exactly one in-process broker node | Verified |
| MOJO-002 | platform handle | Process-local shared-region capability works; native C handle wrapping rejects | Verified boundary |
| MOJO-003 | platform channel | Constructors/endpoints fail explicitly; no fake socketpair, pipe, or descriptor | Explicit unsupported |
| MOJO-004 | ipcz shared buffer | Local capability transfer works; transport serialization rejects | Verified boundary |
| MOJO-005 | local message pipe | Local ipcz portals transfer messages and attached API objects without a transport | Verified |
| MOJO-006 | shared-buffer transfer | C API create/map/attach/send/read/extract/map/verify/modify/close lifecycle | Verified |

## Deferred milestone boundaries

- PartitionAlloc and allocator-shim integration remain deferred while the
  focused M1 graph uses the Emscripten allocator.
- OPFS persistence is not part of MEMFS behavior and begins only at its
  scheduled storage milestone.
- Process spawning/enumeration, native sandboxing, platform channels, remote
  Mojo nodes, dynamic libraries, and executable memory are unavailable.
- V8, Blink, Content, Ozone, networking, media, DevTools, extensions, PDF, and
  Chrome UI remain outside M1.

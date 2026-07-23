# Chromium Wasm product porting ledger

This is the versioned product ledger. It groups blockers by root cause and is
not a compiler-error transcript. The complete machine-readable M1.0 inventory
is [`tools/wasm/m1_inventory.json`](../../tools/wasm/m1_inventory.json).

## Build and source selection

| ID | Target | Root cause | Planned boundary | Status |
|---|---|---|---|---|
| BUILD-001 | M1 smoke graph | M0 reaches only `//wasm:hello_wasm` | Add only passing M1 smoke labels to the opt-in root group | Open |
| BUILD-002 | focused Base subset | `base/BUILD.gn` explicitly rejects Wasm | Permit only the explicit Chromium Wasm port and expose a narrow M1 subset | Open |
| BUILD-003 | platform sources | Base has no `is_wasm` source block | Add one deliberate Wasm source list; do not set Wasm to POSIX/Linux | Open |

## Base platform ABI and primitives

| ID | Capability | Root cause | Planned boundary | Status |
|---|---|---|---|---|
| BASE-ABI-001 | thread types | Headers define no Wasm ID/handle types | Wasm thread ID plus Emscripten pthread handle | Open |
| BASE-ABI-002 | lock/CV types | pthread types are gated on POSIX/Fuchsia | Targeted Wasm header branches and explicit source selection | Open |
| BASE-ABI-003 | VFS descriptor types | integer descriptors are gated on POSIX/Fuchsia | Treat Emscripten VFS descriptors as Wasm platform files | Open |
| BASE-ABI-004 | path/stat types | narrow paths and stat are gated on POSIX/Fuchsia | Targeted Wasm branches backed by MEMFS | Open |
| BASE-ABI-005 | process identity | only native OS handle types exist | One process-local identity; no fake child handles | Open |
| BASE-TIME-001/2/4 | wall, monotonic, and high-resolution behavior | no Wasm provider | `base/time/time_wasm.cc` with accurate resolution | Open |
| BASE-RAND-001 | secure entropy | POSIX provider assumes native entropy | Emscripten `getentropy`, with explicit failure | Open |
| BASE-RAND-002 | nonallocating random API | public header unconditionally includes an unhydrated BoringSSL header | targeted Wasm implementation through `RandBytes` | Open |
| BASE-THREAD-001 | thread operations | POSIX implementation includes native priority behavior | `base/threading/platform_thread_wasm.cc` | Open |
| BASE-THREAD-002 | thread ID/name | native IDs and enforced names are assumed | stable pthread IDs and best-effort diagnostic names | Open |
| BASE-TLS-001 | TLS | pthread source is not selected | Explicitly select and test pthread TLS | Open |
| BASE-SYNC-001/2 | lock, CV, event | pthread sources are not selected | Explicitly select and test worker waits | Open |
| BASE-PATH-001 | platform paths | POSIX source returns host/XDG paths | `base/base_paths_wasm.cc` with VFS paths | Open |
| BASE-FILE-001/2 | file I/O and enumeration | VFS-compatible calls are hidden in POSIX sources | Deliberate MEMFS source selection and behavior tests | Open |
| BASE-PROCESS-001/2 | identity and launch | Base assumes kernel processes | Local ID; launch explicitly unsupported | Open |
| BASE-SYS-001 | system information | native syscalls/procfs | `base/system/sys_info_wasm.cc`, accurate values only | Open |

## Base task runtime

| ID | Capability | Root cause | Planned boundary | Status |
|---|---|---|---|---|
| TASK-001 | default message pump | Generic pump is unreachable and untested on Wasm | Retain it first; validate worker wait/wake, delays, nesting, quit, and heartbeat | Open |
| TASK-002 | task executor | Depends on a valid default pump and Base subset | Run only on the application pthread | Open |

## Rust

| ID | Capability | Root cause | Planned boundary | Status |
|---|---|---|---|---|
| RUST-TOOLCHAIN-001 | compiler install | M0 verifies the DEPS text pin only | Download, hash, extract, and verify the exact archive | Open |
| RUST-TOOLCHAIN-002 | target stdlib | pinned package has no Emscripten stdlib | Build from pinned `rustc-src` through Chromium GN | Open |
| RUST-TOOLCHAIN-003 | pthread codegen | Rust lacks C/C++ Wasm atomics flags | Synchronize target features and link settings | Open |
| RUST-GN-001/2/3 | GN target mapping | Wasm is disabled; triple and arch are absent | Conditional enablement, Emscripten triple, wasm32 arch | Open |
| RUST-LINK-001 | final link | archive compatibility is unverified | rlibs into the Emscripten `em++` final link; no LLVM bitcode | Open |
| RUST-PANIC-001 | panic behavior | target policy is not set | `panic=abort` plus expected-failure runner | Open |
| RUST-ALLOC-001 | allocation/std | System allocator path is unverified | Exercise `Vec`, `String`, allocation, and free | Open |
| RUST-PRELUDE-001 | Chromium prelude | disabled with the M0 Rust configuration | Enable after the target stdlib and run its import test | Open |
| RUST-INTEROP-001 | C++/Rust calls | existing CXX test is not in the Wasm graph | Reuse the pinned Chromium CXX mechanism | Open |
| RUST-THREAD-001 | Rust pthread | target stdlib/thread feature contract is unverified | Spawn/join, atomic handoff, and browser heartbeat | Open |
| RUST-TEST-001 | test runner | native Rust unit-test runner assumption | Dedicated Node/browser smoke first | Deferred |

## Shared memory and Mojo

| ID | Capability | Root cause | Planned boundary | Status |
|---|---|---|---|---|
| SHMEM-001 | handle type | Wasm falls through to an unavailable POSIX `FDPair` | Opaque ID, generation, and rights capability | Open |
| SHMEM-002 | storage/duplication | no kernel shared-memory object exists | Process-local aligned registry with validated references | Open |
| SHMEM-003 | mapping lifetime | native mappings retain kernel storage | Separate mapping references retain registry entries | Open |
| SHMEM-004 | read-only mode | linear memory lacks page protection | Enforce rights at API boundaries and document limitation | Open |
| MOJO-001 | core selection | pinned checkout uses ipcz outside ChromeOS | Keep ipcz and one node; do not enable legacy core | Selected |
| MOJO-002 | platform handle | native handle variants have Wasm `#error` paths | Narrow shared-region capability; native wrap is unsupported | Open |
| MOJO-003 | platform channel | channel assumes a native endpoint | Explicit unsupported Wasm implementation | Open |
| MOJO-004 | ipcz shared buffer | fallback serializes POSIX FDs | Explicit local capability branch; reject remote serialization | Open |
| MOJO-005 | local message pipe | behavior has not run under Wasm | Use local ipcz portals without a transport | Open |
| MOJO-006 | shared-buffer transfer | complete ownership path is untested | C API create/map/attach/send/read/map/close smoke | Open |

## Deferred milestone boundaries

- PartitionAlloc and allocator shim integration are deferred while the focused
  M1 subset uses the Emscripten allocator.
- Process launch, process enumeration, dynamic-library loading, native
  executable memory, platform channels, and remote Mojo nodes remain explicitly
  unsupported.
- OPFS, V8, Blink, Content, Ozone, networking, media, and Chrome UI are outside
  M1.

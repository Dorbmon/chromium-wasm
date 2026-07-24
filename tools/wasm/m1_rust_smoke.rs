// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use std::mem::size_of;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

const CALLBACK_INPUT: u64 = 0x0123_4567_89ab_cdef;
const CALLBACK_MASK: u64 = 0xa5a5_5a5a_dead_beef;
const CALLBACK_WORKER_VALUE: u32 = 0x1357_9bdf;
const EXPECTED_MUTEX_VALUE: u32 = 32;
const EXPECTED_PANIC_MARKER: &str = "chromium_wasm_m1_expected_panic";

static DROP_PROBE_COUNT: AtomicU32 = AtomicU32::new(0);

#[cxx::bridge(namespace = "chromium_wasm::rust_smoke")]
mod ffi {
    pub struct AbiInput {
        pub i8_value: i8,
        pub u8_value: u8,
        pub i16_value: i16,
        pub u16_value: u16,
        pub i32_value: i32,
        pub u32_value: u32,
        pub i64_value: i64,
        pub u64_value: u64,
        pub isize_value: isize,
        pub usize_value: usize,
        pub cookie: u64,
    }

    pub struct RustReport {
        pub signed_64_echo: i64,
        pub unsigned_64_echo: u64,
        pub usize_echo: usize,
        pub callback_token: u64,
        pub pointer_bytes: u32,
        pub atomic_value: u32,
        pub mutex_value: u32,
        pub arc_before_spawn: u32,
        pub arc_after_join: u32,
        pub worker_return: u32,
        pub integer_widths_ok: bool,
        pub thread_spawned: bool,
        pub thread_joined: bool,
    }

    extern "Rust" {
        type DropProbe;

        #[cxx_name = "RunRustSmoke"]
        fn run_rust_smoke(input: AbiInput) -> RustReport;

        #[cxx_name = "MakeRustVector"]
        fn make_rust_vector() -> Vec<u32>;

        #[cxx_name = "MakeRustString"]
        fn make_rust_string() -> String;

        #[cxx_name = "MakeDropProbe"]
        fn make_drop_probe(marker: u64) -> Box<DropProbe>;

        #[cxx_name = "Marker"]
        fn marker(self: &DropProbe) -> u64;

        #[cxx_name = "DropProbeCount"]
        fn drop_probe_count() -> u32;

        #[cxx_name = "TriggerExpectedPanic"]
        fn trigger_expected_panic();
    }

    unsafe extern "C++" {
        include!("tools/wasm/m1_rust_callback.h");

        #[cxx_name = "RustSmokeCppCallback"]
        fn rust_smoke_cpp_callback(value: u64, worker_value: u32) -> u64;
    }
}

struct ThreadState {
    atomic_value: AtomicU32,
    mutex_values: Mutex<Vec<u32>>,
}

struct WorkerOutcome {
    callback_token: u64,
    mutex_updated: bool,
    worker_return: u32,
}

pub struct DropProbe {
    marker: u64,
    payload: Vec<u8>,
    message: String,
}

impl DropProbe {
    pub fn marker(&self) -> u64 {
        if self.payload == [3, 1, 4, 1, 5, 9] && self.message == "chromium-wasm-rust-drop-probe" {
            self.marker
        } else {
            0
        }
    }
}

impl Drop for DropProbe {
    fn drop(&mut self) {
        DROP_PROBE_COUNT.fetch_add(1, Ordering::SeqCst);
    }
}

fn callback_expected() -> u64 {
    CALLBACK_INPUT.rotate_left(13) ^ (u64::from(CALLBACK_WORKER_VALUE) << 32) ^ CALLBACK_MASK ^ 1
}

fn integer_widths_ok(input: &ffi::AbiInput) -> bool {
    size_of::<i8>() == 1
        && size_of::<u8>() == 1
        && size_of::<i16>() == 2
        && size_of::<u16>() == 2
        && size_of::<i32>() == 4
        && size_of::<u32>() == 4
        && size_of::<i64>() == 8
        && size_of::<u64>() == 8
        && size_of::<isize>() == 4
        && size_of::<usize>() == 4
        && input.i8_value == -101
        && input.u8_value == 201
        && input.i16_value == -12_345
        && input.u16_value == 54_321
        && input.i32_value == -123_456_789
        && input.u32_value == 3_456_789_012
        && input.i64_value == -81_985_529_216_486_895
        && input.u64_value == 0xfedc_ba98_7654_3210
        && input.isize_value == -1_234_567
        && input.usize_value == 0x89ab_cdef
        && input.cookie == 0xc001_d00d_c0de_cafe
}

pub fn run_rust_smoke(input: ffi::AbiInput) -> ffi::RustReport {
    let mut report = ffi::RustReport {
        signed_64_echo: input.i64_value,
        unsigned_64_echo: input.u64_value,
        usize_echo: input.usize_value,
        callback_token: 0,
        pointer_bytes: size_of::<usize>() as u32,
        atomic_value: 0,
        mutex_value: 0,
        arc_before_spawn: 0,
        arc_after_join: 0,
        worker_return: 0,
        integer_widths_ok: integer_widths_ok(&input),
        thread_spawned: false,
        thread_joined: false,
    };

    let state = Arc::new(ThreadState {
        atomic_value: AtomicU32::new(7),
        mutex_values: Mutex::new(vec![1]),
    });
    let worker_state = Arc::clone(&state);
    report.arc_before_spawn = Arc::strong_count(&state) as u32;

    let worker = match thread::Builder::new().spawn(move || {
        thread::sleep(Duration::from_millis(250));
        let callback_token = ffi::rust_smoke_cpp_callback(CALLBACK_INPUT, CALLBACK_WORKER_VALUE);
        worker_state.atomic_value.fetch_add(35, Ordering::Release);
        let mutex_updated = match worker_state.mutex_values.lock() {
            Ok(mut values) => {
                values.extend_from_slice(&[2, 3, 5, 8, 13]);
                true
            }
            Err(_) => false,
        };
        WorkerOutcome { callback_token, mutex_updated, worker_return: CALLBACK_WORKER_VALUE }
    }) {
        Ok(worker) => worker,
        Err(_) => {
            report.arc_after_join = Arc::strong_count(&state) as u32;
            return report;
        }
    };
    report.thread_spawned = true;

    if let Ok(outcome) = worker.join() {
        report.thread_joined = true;
        report.callback_token =
            if outcome.callback_token == callback_expected() { outcome.callback_token } else { 0 };
        report.worker_return = outcome.worker_return;
        if outcome.mutex_updated {
            let mutex_value = match state.mutex_values.lock() {
                Ok(values) => values.iter().copied().sum(),
                Err(_) => 0,
            };
            report.mutex_value = if mutex_value == EXPECTED_MUTEX_VALUE { mutex_value } else { 0 };
        }
    }

    report.atomic_value = state.atomic_value.load(Ordering::Acquire);
    report.arc_after_join = Arc::strong_count(&state) as u32;
    report
}

pub fn make_rust_vector() -> Vec<u32> {
    vec![3, 5, 8, 13, 21, 34]
}

pub fn make_rust_string() -> String {
    "chromium-wasm-rust-string-allocation".to_owned()
}

pub fn make_drop_probe(marker: u64) -> Box<DropProbe> {
    Box::new(DropProbe {
        marker,
        payload: vec![3, 1, 4, 1, 5, 9],
        message: "chromium-wasm-rust-drop-probe".to_owned(),
    })
}

pub fn drop_probe_count() -> u32 {
    DROP_PROBE_COUNT.load(Ordering::SeqCst)
}

#[inline(never)]
pub fn trigger_expected_panic() {
    panic!("{EXPECTED_PANIC_MARKER}");
}

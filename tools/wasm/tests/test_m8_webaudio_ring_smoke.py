#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused contracts for the target-local M8 WebAudio ring feasibility smoke.

These are source and host-boundary contracts only. They deliberately do not
launch a browser, invoke a Wasm export, or claim Chromium media integration.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from m0_common import M0Error
import run_m8_webaudio_ring_smoke as smoke
from tools.wasm.tests.m3_source_contract_test_support import source


def passing_result() -> dict[str, object]:
    result: dict[str, object] = {field: False for field in smoke.RESULT_KEYS}
    result.update(
        {
            "protocol": smoke.HOST_PROTOCOL,
            "case": smoke.CASE,
            "scope": smoke.SCOPE,
            "status": "pass",
            "failureCode": None,
            "secureContext": True,
            "crossOriginIsolated": True,
            "sharedArrayBuffer": True,
            "descriptorProtocol": smoke.DESCRIPTOR_PROTOCOL,
            "channels": smoke.CHANNELS,
            "totalFrames": smoke.TOTAL_FRAMES,
            "descriptorValidated": True,
            "memoryGrowthPolicy": "reject-on-any-memory-growth",
            "memoryGrowthSignals": 0,
            "memoryGrowthRejected": False,
            "memoryIdentityChecks": 9,
            "memoryIdentityStable": True,
            "nativeReady": True,
            "nativeProducerStartedMarker": True,
            "nativeProducerDoneMarker": True,
            "runtimeInitialized": True,
            "runtimeFactorySettled": True,
            "runtimeAborted": False,
            "runtimeExited": False,
            "trustedGesture": True,
            "resumeRequestedInTrustedGesture": True,
            "audioContextRunning": True,
            "workletReady": True,
            "workletProgressObserved": True,
            "workletDrained": True,
            "workletUnderrunFrames": 0,
            "producerStarted": True,
            "producerFinished": True,
            "startRequested": True,
            "workletStopRequested": True,
            "nodeDisconnected": True,
            "audioContextClosed": True,
            "cleanupComplete": True,
            "m8GateComplete": False,
            "chromiumAudioManagerIntegrated": False,
            "chromiumAudioServiceIntegrated": False,
            "chromiumMediaSchedulingPreserved": False,
            "muteVolumeDevicePolicyProven": False,
            "tabSwitchingProven": False,
            "browserMediaPlaybackProven": False,
            "normalRuntimeShutdownProven": False,
        }
    )
    assert set(result) == smoke.RESULT_KEYS
    return result


class M8WebAudioRingResultContractTest(unittest.TestCase):
    def test_accepts_only_complete_feasibility_evidence(self) -> None:
        smoke.validate_result(passing_result())

    def test_rejects_memory_growth_or_media_integration_claims(self) -> None:
        for field, value in (
            ("memoryGrowthSignals", 1),
            ("memoryGrowthRejected", True),
            ("memoryIdentityStable", False),
            ("memoryIdentityChecks", 0),
            ("chromiumAudioManagerIntegrated", True),
            ("browserMediaPlaybackProven", True),
        ):
            with self.subTest(field=field):
                result = passing_result()
                result[field] = value
                with self.assertRaises(M0Error):
                    smoke.validate_result(result)

    def test_failure_payload_is_fixed_and_cannot_carry_extra_data(self) -> None:
        result = passing_result()
        result["status"] = "fail"
        result["failureCode"] = "memory-growth-rejected"
        self.assertTrue(smoke._is_result_payload(result))

        result["arbitraryError"] = "not allowed"
        self.assertFalse(smoke._is_result_payload(result))

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            smoke._json_object_without_duplicate_keys(
                [("protocol", 1), ("protocol", 1)]
            )


class M8WebAudioRingServerContractTest(unittest.TestCase):
    def test_exact_artifact_allowlist_and_isolation_headers(self) -> None:
        token = "a" * 24
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary)
            (out_dir / f"{smoke.MODULE_NAME}.js").write_text(
                "export default () => ({});\n", encoding="utf-8"
            )
            (out_dir / f"{smoke.MODULE_NAME}.wasm").write_bytes(b"\0asm")
            ready_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            result_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
            server = smoke.create_server(
                "127.0.0.1", 0, out_dir, token, ready_queue, result_queue
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address[:2]
                base = f"http://{host}:{port}{smoke.HOST_ROOT}"
                with urlopen(base + "/") as response:
                    self.assertEqual(response.status, HTTPStatus.OK)
                    self.assertEqual(
                        response.headers["Cross-Origin-Opener-Policy"],
                        "same-origin",
                    )
                    self.assertEqual(
                        response.headers["Cross-Origin-Embedder-Policy"],
                        "require-corp",
                    )
                    self.assertEqual(
                        response.headers["Cross-Origin-Resource-Policy"],
                        "same-origin",
                    )
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(
                        response.headers["X-Content-Type-Options"], "nosniff"
                    )
                    self.assertIn("text/html", response.headers["Content-Type"])

                with urlopen(
                    base + f"/artifacts/{smoke.MODULE_NAME}.wasm"
                ) as response:
                    self.assertEqual(response.status, HTTPStatus.OK)
                    self.assertEqual(
                        response.headers["Content-Type"], "application/wasm"
                    )
                    self.assertEqual(response.read(), b"\0asm")

                for forbidden in (
                    base + "/artifacts/other.wasm",
                    base + f"/artifacts/{smoke.MODULE_NAME}.data",
                    base + "/run_m8_webaudio_ring_smoke.py",
                ):
                    with self.subTest(forbidden=forbidden):
                        with self.assertRaises(HTTPError) as error:
                            urlopen(forbidden)
                        self.assertEqual(error.exception.code, HTTPStatus.NOT_FOUND)
                        error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_smoke_url_has_only_the_fixed_route_and_query(self) -> None:
        class Server:
            server_address = ("127.0.0.1", 43127)
            token = "b" * 24

        url = smoke.smoke_url(Server(), "b" * 24, 45.0)
        self.assertEqual(
            url,
            "http://127.0.0.1:43127/__m8_webaudio_ring__/"
            + "?token="
            + "b" * 24
            + "&timeoutMs=45000",
        )


class M8WebAudioRingSourceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.build = source("tools/wasm/BUILD.gn")
        self.wasm_config = source("build/config/wasm.gni")
        self.native = source("tools/wasm/m8_webaudio_ring_smoke.cc")
        self.bridge = source("tools/wasm/m8_webaudio_ring_bridge.js")
        self.host = source("tools/wasm/host/m8_webaudio_ring_smoke.js")
        self.worklet = source("tools/wasm/host/m8_webaudio_ring_worklet.js")
        self.html = source("tools/wasm/host/m8_webaudio_ring_smoke.html")
        self.runner = source("tools/wasm/run_m8_webaudio_ring_smoke.py")

    def test_target_isolated_from_chromium_media(self) -> None:
        self.assertIn('executable("m8_webaudio_ring_smoke")', self.build)
        self.assertIn('sources = [ "m8_webaudio_ring_smoke.cc" ]', self.build)
        self.assertIn('inputs = [ "m8_webaudio_ring_bridge.js" ]', self.build)
        self.assertIn("no_default_deps = true", self.build)
        self.assertNotIn('#include "media/', self.native)
        self.assertIn("neither Chromium's AudioManager nor AudioService", self.native)

    def test_exact_descriptor_protocol_and_bounds_are_checked(self) -> None:
        for text in (self.native, self.bridge, self.host, self.worklet):
            with self.subTest(source=text[:40]):
                self.assertIn("4096", text)
                self.assertIn("12288", text)
                self.assertIn("channels", text)
        for token in (
            "hasExactKeys(descriptor",
            "Atomics.load(header, index)",
            "headerEnd > samplesOffset && samplesEnd > headerOffset",
            "validated.ringBuffer !== this.wasmMemory.buffer",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.host)
        self.assertIn("Atomics.load(headerWords, 11) !== 0", self.bridge)
        self.assertIn("(headerEnd > samples && samplesEnd > header)", self.bridge)
        self.assertIn("this.ringBufferByteLength", self.worklet)
        self.assertIn("headerEnd > this.samplesByteOffset", self.worklet)

    def test_trusted_gesture_starts_resume_before_async_worklet_setup(self) -> None:
        trusted = self.host.index("event.isTrusted !== true")
        resume = self.host.index("const resumePromise = context.resume();")
        worklet = self.host.index("context.audioWorklet.addModule")
        self.assertLess(trusted, resume)
        self.assertLess(resume, worklet)
        self.assertIn("new AudioWorkletNode", self.host)
        self.assertIn(
            "dispatch_primary_click(START_BUTTON_X, START_BUTTON_Y)",
            self.runner,
        )
        self.assertNotIn("Runtime.evaluate", self.runner)
        self.assertNotIn(".click()", self.runner)

    def test_memory_identity_is_observed_without_an_inert_runtime_hook(self) -> None:
        for token in (
            "initial: WASM_INITIAL_PAGES",
            "maximum: WASM_MAXIMUM_PAGES",
            "shared: true",
            "wasmMemory: this.wasmMemory",
            "setInterval(() => {",
            "currentBuffer === this.ringBuffer",
            "currentBuffer.byteLength === this.ringBufferByteLength",
            "this.stopMemoryWatchdog()",
            "this.clearRingViews()",
            'this.setFailure("memory-growth-rejected")',
            "memoryIdentityChecks",
            "memoryIdentityStable",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.host)
        self.assertNotIn("onMemoryGrowth", self.host)
        self.assertIn("hasStableMemoryIdentity", self.bridge)
        self.assertIn("bridge.verifyMemoryIdentity() === true", self.bridge)
        self.assertIn(
            "this.ringBuffer.byteLength !== this.ringBufferByteLength",
            self.worklet,
        )
        self.assertIn(
            "chromium_wasm_initial_memory_bytes = 67108864", self.wasm_config
        )
        self.assertIn(
            "chromium_wasm_maximum_memory_bytes = 2147483648", self.wasm_config
        )
        self.assertIn("const WASM_INITIAL_PAGES = 1024;", self.host)
        self.assertIn("const WASM_MAXIMUM_PAGES = 32768;", self.host)

    def test_async_native_markers_converge_before_success(self) -> None:
        self.assertIn("nativeProducerMarkersSignal", self.host)
        self.assertIn("maybeResolveNativeProducerMarkers", self.host)
        self.assertIn('"native-marker-timeout"', self.host)
        self.assertIn(
            "await this.awaitSignalOrFailure(this.nativeProducerMarkersSignal.promise",
            self.host,
        )
        self.assertIn("!this.nativeProducerStartedMarker", self.host)
        self.assertIn("!this.nativeReady || this.nativeProducerStartedMarker", self.host)
        self.assertNotIn("delay(0)", self.host)

    def test_module_loading_and_posts_are_bounded_by_the_run_deadline(self) -> None:
        self.assertIn(
            "await awaitBeforeDeadline(fetch(moduleUrl.href, {", self.host
        )
        self.assertIn(
            'response.blob(), this.deadline, "module-loader-failed"', self.host
        )
        self.assertIn(
            'import(moduleUrl.href), this.deadline, "module-loader-failed"',
            self.host,
        )
        self.assertIn(
            "await awaitBeforeDeadline(fetch(endpoint.href, {", self.host
        )
        self.assertIn(
            "await awaitBeforeDeadline(this.loadRuntime(), this.deadline,",
            self.host,
        )

    def test_server_and_host_do_not_leak_raw_exception_or_output_text(self) -> None:
        for text in (self.bridge, self.host, self.worklet, self.html):
            for forbidden in (
                "String(error)",
                "error.message",
                "console.error",
                "console.log",
                "throw error",
            ):
                with self.subTest(forbidden=forbidden, source=text[:40]):
                    self.assertNotIn(forbidden, text)
        self.assertIn("stdout=subprocess.DEVNULL", self.runner)
        self.assertIn("stderr=subprocess.DEVNULL", self.runner)
        self.assertNotIn("stderr_tail", self.runner)
        self.assertIn(
            'if name not in {f"{MODULE_NAME}.js", f"{MODULE_NAME}.wasm"}',
            self.runner,
        )
        self.assertIn('"Cross-Origin-Opener-Policy", "same-origin"', self.runner)
        self.assertIn('"Cross-Origin-Embedder-Policy", "require-corp"', self.runner)

    def test_result_makes_nonclaims_explicit(self) -> None:
        for field in (
            "m8GateComplete",
            "chromiumAudioManagerIntegrated",
            "chromiumAudioServiceIntegrated",
            "chromiumMediaSchedulingPreserved",
            "muteVolumeDevicePolicyProven",
            "tabSwitchingProven",
            "browserMediaPlaybackProven",
            "normalRuntimeShutdownProven",
        ):
            with self.subTest(field=field):
                self.assertIn(f"{field}: false", self.host)
                self.assertIn(f'"{field}"', self.runner)

    def test_node_fake_host_checks_click_markers_and_memory_guard(self) -> None:
        host_uri = (
            TOOLS_DIR / "host" / "m8_webaudio_ring_smoke.js"
        ).as_uri()
        script = r'''
class FakeElement {
  constructor() {
    this.dataset = {};
    this.textContent = "";
  }
}
class FakeButton extends FakeElement {
  constructor() {
    super();
    this.disabled = false;
  }
  addEventListener(_name, callback) {
    this.callback = callback;
  }
}
globalThis.HTMLElement = FakeElement;
globalThis.HTMLButtonElement = FakeButton;
const root = new FakeElement();
const status = new FakeElement();
const button = new FakeButton();
globalThis.document = {
  querySelector(selector) {
    return selector === "#m8-webaudio-root" ? root :
        selector === "#m8-webaudio-status" ? status :
        selector === "#m8-webaudio-start" ? button : null;
  },
};
let resumeCalls = 0;
globalThis.AudioContext = class {
  constructor() {
    this.state = "running";
    this.audioWorklet = {addModule: () => new Promise(() => {})};
  }
  resume() {
    ++resumeCalls;
    return new Promise(() => {});
  }
};
globalThis.AudioWorkletNode = class {};

const {M8WebAudioRingSmoke} = await import(process.argv[1]);
function probe() {
  const value = new M8WebAudioRingSmoke({
    token: "a".repeat(24),
    timeoutMs: 1000,
  });
  value.wasmMemory = new WebAssembly.Memory({
    initial: 1024,
    maximum: 32768,
    shared: true,
  });
  return value;
}

const trusted = probe();
trusted.startButton.disabled = false;
trusted.onStartClick({isTrusted: true});
if (resumeCalls !== 1 || !trusted.trustedGesture ||
    !trusted.resumeRequestedInTrustedGesture) {
  throw new Error("trusted resume was not synchronous");
}
const untrusted = probe();
untrusted.onStartClick({isTrusted: false});
if (untrusted.failureCode !== "trusted-gesture-invalid") {
  throw new Error("untrusted click was accepted");
}

const markers = probe();
let markersResolved = false;
markers.nativeProducerMarkersSignal.promise.then(() => {
  markersResolved = true;
});
markers.observeNativeOutput(
    "CHROMIUM_WASM_M8_WEBAUDIO_RING:READY capacity_frames=4096 channels=2 total_frames=12288");
markers.observeNativeOutput(
    "CHROMIUM_WASM_M8_WEBAUDIO_RING:PRODUCER_STARTED");
await Promise.resolve();
if (markersResolved) {
  throw new Error("single marker resolved convergence");
}
markers.observeNativeOutput(
    "CHROMIUM_WASM_M8_WEBAUDIO_RING:PRODUCER_DONE frames=12288");
await Promise.resolve();
if (!markersResolved) {
  throw new Error("both markers did not converge");
}

const outOfOrder = probe();
outOfOrder.observeNativeOutput(
    "CHROMIUM_WASM_M8_WEBAUDIO_RING:PRODUCER_DONE frames=12288");
if (outOfOrder.failureCode !== "native-output-invalid") {
  throw new Error("done-before-start marker was accepted");
}

const memory = probe();
const header = new Int32Array(memory.wasmMemory.buffer, 0, 12);
header[0] = 1;
header[1] = 4096;
header[2] = 2;
if (!memory.registerRing({
  protocol: 1,
  ringBuffer: memory.wasmMemory.buffer,
  headerByteOffset: 0,
  samplesByteOffset: 64,
  capacityFrames: 4096,
  channels: 2,
  totalFrames: 12288,
})) {
  throw new Error("fixed descriptor was rejected");
}
memory.wasmMemory.grow(1);
if (memory.verifyMemoryIdentity() ||
    memory.failureCode !== "memory-growth-rejected" ||
    memory.ringBuffer !== null || memory.header !== null ||
    memory.samples !== null) {
  throw new Error("memory identity change did not fail closed");
}
const nonclaims = probe().makeResult();
if (nonclaims.chromiumAudioManagerIntegrated ||
    nonclaims.chromiumAudioServiceIntegrated ||
    nonclaims.browserMediaPlaybackProven) {
  throw new Error("result has an integration claim");
}
'''
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script, host_uri],
            capture_output=True,
            check=False,
            cwd=TOOLS_DIR.parents[1],
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()

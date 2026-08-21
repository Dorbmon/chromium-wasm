// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Target-local M8 WebAudio feasibility host. This deliberately proves only a
// C++ pthread producer, one bounded SharedArrayBuffer PCM ring, and one host
// AudioWorklet consumer. It does not select Chromium's AudioManager or
// AudioService, and it makes no browser-media playback claim.

export const HOST_PROTOCOL = 1;
export const CASE = "m8_webaudio_ring";
export const SCOPE =
    "target-local-cpp-pthread-shared-memory-ring-to-host-audioworklet";
export const MODULE_NAME = "m8_webaudio_ring_smoke";
export const DESCRIPTOR_PROTOCOL = 1;
export const HEADER_WORDS = 12;
export const CAPACITY_FRAMES = 4096;
export const CHANNELS = 2;
export const TOTAL_FRAMES = 12288;
export const START_BUTTON_X = 120;
export const START_BUTTON_Y = 48;

const HOST_BRIDGE_NAME = "__chromiumWasmM8WebAudioRingHostV1";
const MAX_TIMEOUT_MS = 90000;
const MIN_TIMEOUT_MS = 1000;
const CLEANUP_TIMEOUT_MS = 2500;
const MEMORY_WATCHDOG_MS = 25;
const WASM_PAGE_BYTES = 64 * 1024;
const WASM_INITIAL_PAGES = 1024;
const WASM_MAXIMUM_PAGES = 32768;
const WASM_INITIAL_BYTES = WASM_PAGE_BYTES * WASM_INITIAL_PAGES;
const MAX_UNDERRUN_FRAMES = 1 << 20;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
const READY_MARKER =
    "CHROMIUM_WASM_M8_WEBAUDIO_RING:READY capacity_frames=4096 " +
    "channels=2 total_frames=12288";
const PRODUCER_STARTED_MARKER =
    "CHROMIUM_WASM_M8_WEBAUDIO_RING:PRODUCER_STARTED";
const PRODUCER_DONE_MARKER =
    "CHROMIUM_WASM_M8_WEBAUDIO_RING:PRODUCER_DONE frames=12288";
const NATIVE_PREFIX = "CHROMIUM_WASM_M8_WEBAUDIO_RING:";
const START_REQUESTED = 3;
const PRODUCER_STARTED = 4;
const PRODUCER_DONE = 5;
const WRITE_FRAME = 6;
const READ_FRAME = 7;
const PRODUCED_FRAMES = 8;
const CONSUMED_FRAMES = 9;
const UNDERRUN_FRAMES = 10;
const PRODUCER_ERROR = 11;

const FAILURE_CODES = new Set([
  "audio-context-close-failed",
  "audio-context-create-failed",
  "audio-context-not-running",
  "descriptor-invalid",
  "descriptor-duplicate",
  "document-prerequisite",
  "factory-failed",
  "host-exception",
  "memory-growth-rejected",
  "module-loader-failed",
  "native-marker-timeout",
  "native-output-invalid",
  "native-runtime-abort",
  "native-runtime-exited",
  "producer-report-invalid",
  "result-post-failed",
  "runtime-startup-timeout",
  "trusted-gesture-invalid",
  "wasm-memory-create-failed",
  "worklet-add-module-failed",
  "worklet-drain-invalid",
  "worklet-drain-timeout",
  "worklet-node-create-failed",
  "worklet-protocol-invalid",
  "worklet-runtime-failed",
]);

const WORKLET_ERROR_CODES = new Set([
  "invalid-descriptor",
  "invalid-output",
  "invalid-ring",
  "invalid-sample",
  "processor-exception",
]);

class RingSmokeError extends Error {
  constructor(code) {
    super(code);
    this.code = FAILURE_CODES.has(code) ? code : "host-exception";
  }
}

function fail(code) {
  throw new RingSmokeError(code);
}

function fixedFailureCode(error) {
  return error instanceof RingSmokeError ? error.code : "host-exception";
}

function hasExactKeys(value, keys) {
  if (value === null || typeof value !== "object" ||
      Object.getPrototypeOf(value) !== Object.prototype) {
    return false;
  }
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length &&
      actual.every((key, index) => key === expected[index]);
}

function isSafeIntegerInRange(value, minimum, maximum) {
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

function oneQueryValue(query, name) {
  const values = query.getAll(name);
  if (values.length !== 1 || values[0] === "") {
    fail("document-prerequisite");
  }
  return values[0];
}

function parseTimeout(value) {
  if (!/^[0-9]+$/.test(value)) {
    fail("document-prerequisite");
  }
  const timeout = Number(value);
  if (!isSafeIntegerInRange(timeout, MIN_TIMEOUT_MS, MAX_TIMEOUT_MS)) {
    fail("document-prerequisite");
  }
  return timeout;
}

export function parseM8WebAudioRingContext(search) {
  const query = new URLSearchParams(search);
  for (const name of query.keys()) {
    if (name !== "token" && name !== "timeoutMs") {
      fail("document-prerequisite");
    }
  }
  const token = oneQueryValue(query, "token");
  if (!TOKEN_RE.test(token)) {
    fail("document-prerequisite");
  }
  return Object.freeze({
    token,
    timeoutMs: parseTimeout(oneQueryValue(query, "timeoutMs")),
  });
}

function documentPrerequisites() {
  return globalThis.isSecureContext === true &&
      globalThis.crossOriginIsolated === true &&
      typeof SharedArrayBuffer === "function" &&
      typeof WebAssembly === "object" &&
      typeof WebAssembly.Memory === "function" &&
      typeof AudioContext === "function" &&
      typeof AudioWorkletNode === "function" &&
      typeof fetch === "function";
}

function setDocumentState(state) {
  const root = document.querySelector("#m8-webaudio-root");
  const status = document.querySelector("#m8-webaudio-status");
  if (root instanceof HTMLElement) {
    root.dataset.state = state;
  }
  if (status instanceof HTMLElement) {
    const fixedStatus = {
      "awaiting-ring": "Waiting for the Wasm ring…",
      "awaiting-trusted-click": "Ready for a trusted Start audio ring click.",
      "starting-audio": "Starting the AudioWorklet…",
      "streaming": "Draining the bounded PCM ring…",
      "pass": "WebAudio ring feasibility probe passed.",
      "fail": "WebAudio ring feasibility probe failed.",
    };
    status.textContent = fixedStatus[state] || "WebAudio ring feasibility probe.";
  }
}

function getStartButton() {
  const button = document.querySelector("#m8-webaudio-start");
  if (!(button instanceof HTMLButtonElement)) {
    fail("document-prerequisite");
  }
  return button;
}

function deadlineAfter(timeoutMs) {
  return performance.now() + timeoutMs;
}

async function awaitBeforeDeadline(promise, deadline, code) {
  const remaining = Math.floor(deadline - performance.now());
  if (remaining <= 0) {
    fail(code);
  }
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new RingSmokeError(code)), remaining);
  });
  try {
    return await Promise.race([Promise.resolve(promise), timeout]);
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
  }
}

function makeDeferred() {
  let resolve;
  const promise = new Promise((resolver) => {
    resolve = resolver;
  });
  return {promise, resolve};
}

function validateDescriptor(descriptor) {
  if (!hasExactKeys(descriptor, [
    "capacityFrames",
    "channels",
    "headerByteOffset",
    "protocol",
    "ringBuffer",
    "samplesByteOffset",
    "totalFrames",
  ]) || descriptor.protocol !== DESCRIPTOR_PROTOCOL ||
      descriptor.capacityFrames !== CAPACITY_FRAMES ||
      descriptor.channels !== CHANNELS || descriptor.totalFrames !== TOTAL_FRAMES ||
      !(descriptor.ringBuffer instanceof SharedArrayBuffer)) {
    fail("descriptor-invalid");
  }
  const headerOffset = descriptor.headerByteOffset;
  const samplesOffset = descriptor.samplesByteOffset;
  const headerBytes = HEADER_WORDS * Int32Array.BYTES_PER_ELEMENT;
  const sampleBytes = CAPACITY_FRAMES * CHANNELS * Float32Array.BYTES_PER_ELEMENT;
  const headerEnd = headerOffset + headerBytes;
  const samplesEnd = samplesOffset + sampleBytes;
  if (!isSafeIntegerInRange(headerOffset, 0, descriptor.ringBuffer.byteLength) ||
      !isSafeIntegerInRange(samplesOffset, 0, descriptor.ringBuffer.byteLength) ||
      (headerOffset & 3) !== 0 || (samplesOffset & 3) !== 0 ||
      !Number.isSafeInteger(headerEnd) || !Number.isSafeInteger(samplesEnd) ||
      headerEnd < headerOffset || samplesEnd < samplesOffset ||
      headerEnd > descriptor.ringBuffer.byteLength ||
      samplesEnd > descriptor.ringBuffer.byteLength ||
      (headerEnd > samplesOffset && samplesEnd > headerOffset)) {
    fail("descriptor-invalid");
  }
  const header = new Int32Array(descriptor.ringBuffer, headerOffset, HEADER_WORDS);
  const expectedHeader = [
    DESCRIPTOR_PROTOCOL,
    CAPACITY_FRAMES,
    CHANNELS,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
  ];
  if (expectedHeader.some((value, index) => Atomics.load(header, index) !== value)) {
    fail("descriptor-invalid");
  }
  return Object.freeze({
    protocol: DESCRIPTOR_PROTOCOL,
    ringBuffer: descriptor.ringBuffer,
    header,
    samples: new Float32Array(descriptor.ringBuffer, samplesOffset,
                              CAPACITY_FRAMES * CHANNELS),
    headerByteOffset: headerOffset,
    samplesByteOffset: samplesOffset,
  });
}

function createWasmMemory() {
  try {
    const memory = new WebAssembly.Memory({
      initial: WASM_INITIAL_PAGES,
      maximum: WASM_MAXIMUM_PAGES,
      shared: true,
    });
    if (!(memory.buffer instanceof SharedArrayBuffer) ||
        memory.buffer.byteLength !== WASM_INITIAL_BYTES) {
      fail("wasm-memory-create-failed");
    }
    return memory;
  } catch (error) {
    fail(fixedFailureCode(error) === "host-exception" ?
        "wasm-memory-create-failed" : fixedFailureCode(error));
  }
}

function exactWorkletReady(message) {
  return hasExactKeys(message, ["protocol", "type"]) &&
      message.protocol === DESCRIPTOR_PROTOCOL && message.type === "ready";
}

function exactWorkletError(message) {
  return hasExactKeys(message, ["code", "protocol", "type"]) &&
      message.protocol === DESCRIPTOR_PROTOCOL && message.type === "error" &&
      WORKLET_ERROR_CODES.has(message.code);
}

function validWorkletProgress(message) {
  if (!hasExactKeys(message, [
    "framesRead",
    "nonSilentFrames",
    "processCalls",
    "protocol",
    "startRequested",
    "type",
    "underrunFrames",
  ]) || message.protocol !== DESCRIPTOR_PROTOCOL || message.type !== "progress" ||
      typeof message.startRequested !== "boolean") {
    return false;
  }
  return ["framesRead", "nonSilentFrames", "processCalls", "underrunFrames"].every(
      (field) => isSafeIntegerInRange(message[field], 0, MAX_UNDERRUN_FRAMES));
}

function validWorkletDrained(message) {
  return hasExactKeys(message, [
    "framesRead",
    "nonSilentFrames",
    "processCalls",
    "producerDone",
    "producerStarted",
    "protocol",
    "type",
    "underrunFrames",
  ]) && message.protocol === DESCRIPTOR_PROTOCOL && message.type === "drained" &&
      message.framesRead === TOTAL_FRAMES &&
      message.nonSilentFrames === TOTAL_FRAMES &&
      message.producerStarted === true && message.producerDone === true &&
      isSafeIntegerInRange(message.processCalls, 1, MAX_UNDERRUN_FRAMES) &&
      isSafeIntegerInRange(message.underrunFrames, 0, MAX_UNDERRUN_FRAMES);
}

export class M8WebAudioRingSmoke {
  constructor(context) {
    this.context = context;
    this.deadline = deadlineAfter(context.timeoutMs);
    this.startButton = getStartButton();
    this.startButton.disabled = true;
    this.startButton.addEventListener("click", (event) => this.onStartClick(event));

    this.factorySettled = false;
    this.runtimeInitialized = false;
    this.runtimeExited = false;
    this.runtimeAborted = false;
    this.nativeReady = false;
    this.nativeProducerStartedMarker = false;
    this.nativeProducerDoneMarker = false;
    this.descriptorValidated = false;
    this.ringBuffer = null;
    this.header = null;
    this.samples = null;
    this.wasmMemory = null;
    this.ringBufferByteLength = null;
    this.memoryWatchdog = null;
    this.memoryIdentityChecks = 0;
    this.memoryIdentityStable = false;
    this.memoryGrowthSignals = 0;
    this.memoryGrowthRejected = false;
    this.trustedGesture = false;
    this.resumeRequestedInTrustedGesture = false;
    this.audioContextRunning = false;
    this.workletReady = false;
    this.workletProgressObserved = false;
    this.workletDrained = false;
    this.workletUnderrunFrames = null;
    this.producerStarted = false;
    this.producerFinished = false;
    this.startRequested = false;
    this.workletStopRequested = false;
    this.nodeDisconnected = false;
    this.audioContextClosed = false;
    this.cleanupComplete = false;
    this.failureCode = null;
    this.readyPosted = false;
    this.finished = false;
    this.audioContext = null;
    this.workletNode = null;
    this.bridge = Object.freeze({
      protocol: DESCRIPTOR_PROTOCOL,
      registerRing: (descriptor) => this.registerRing(descriptor),
      reportProducerStarted: () => this.reportProducerStarted(),
      reportProducerFinished: (frames) => this.reportProducerFinished(frames),
      verifyMemoryIdentity: () => this.verifyMemoryIdentity(),
    });
    this.readyForClick = makeDeferred();
    this.completion = makeDeferred();
    this.workletReadySignal = makeDeferred();
    this.workletDrainSignal = makeDeferred();
    this.nativeProducerMarkersSignal = makeDeferred();
  }

  setFailure(code) {
    const safeCode = FAILURE_CODES.has(code) ? code : "host-exception";
    if (this.failureCode !== null) {
      return;
    }
    this.failureCode = safeCode;
    if (!this.finished) {
      this.finished = true;
      this.completion.resolve(false);
    }
  }

  setSuccess() {
    if (this.failureCode !== null || this.finished) {
      return;
    }
    this.finished = true;
    this.completion.resolve(true);
  }

  clearRingViews() {
    this.header = null;
    this.samples = null;
    this.ringBuffer = null;
    this.ringBufferByteLength = null;
  }

  startMemoryWatchdog() {
    if (this.memoryWatchdog !== null) {
      this.setFailure("host-exception");
      return;
    }
    this.memoryWatchdog = setInterval(() => {
      this.verifyMemoryIdentity();
    }, MEMORY_WATCHDOG_MS);
  }

  stopMemoryWatchdog() {
    if (this.memoryWatchdog !== null) {
      clearInterval(this.memoryWatchdog);
      this.memoryWatchdog = null;
    }
  }

  verifyMemoryIdentity() {
    if (this.failureCode !== null || this.wasmMemory === null) {
      return false;
    }
    this.memoryIdentityChecks += 1;
    let currentBuffer;
    try {
      currentBuffer = this.wasmMemory.buffer;
    } catch (_error) {
      this.rejectMemoryIdentityChange();
      return false;
    }
    const hasExpectedInitialMemory =
        currentBuffer instanceof SharedArrayBuffer &&
        currentBuffer.byteLength === WASM_INITIAL_BYTES;
    const hasStableRing = this.ringBuffer === null ||
        (this.ringBufferByteLength === WASM_INITIAL_BYTES &&
         currentBuffer === this.ringBuffer &&
         this.ringBuffer.byteLength === this.ringBufferByteLength &&
         currentBuffer.byteLength === this.ringBufferByteLength);
    if (!hasExpectedInitialMemory || !hasStableRing) {
      this.rejectMemoryIdentityChange();
      return false;
    }
    this.memoryIdentityStable = true;
    return true;
  }

  stopWorkletNow() {
    if (this.workletNode !== null) {
      // Record that teardown was requested even when a drained worklet has
      // already made its port unavailable by the time cleanup runs.
      this.workletStopRequested = true;
      try {
        this.workletNode.port.postMessage({
          protocol: DESCRIPTOR_PROTOCOL,
          type: "stop",
        });
      } catch (_error) {
        // Cleanup remains fail-closed without exposing arbitrary exceptions.
      }
      try {
        this.workletNode.disconnect();
        this.nodeDisconnected = true;
      } catch (_error) {
        // The later context close remains the final cleanup attempt.
      }
    }
  }

  rejectMemoryIdentityChange() {
    this.memoryGrowthSignals += 1;
    // A ring descriptor contains typed views into the current Wasm memory.
    // AudioWorklet cannot safely hot-swap that backing buffer. Do not retain
    // the old HEAPU8 buffer: disconnect, clear every view, and reject this run.
    this.memoryGrowthRejected = true;
    this.memoryIdentityStable = false;
    this.stopWorkletNow();
    this.clearRingViews();
    this.setFailure("memory-growth-rejected");
  }

  registerRing(descriptor) {
    if (this.descriptorValidated) {
      this.setFailure("descriptor-duplicate");
      return false;
    }
    try {
      const validated = validateDescriptor(descriptor);
      if (this.wasmMemory === null ||
          validated.ringBuffer !== this.wasmMemory.buffer ||
          validated.ringBuffer.byteLength !== WASM_INITIAL_BYTES) {
        fail("memory-growth-rejected");
      }
      if (this.failureCode !== null || this.finished) {
        return false;
      }
      this.ringBuffer = validated.ringBuffer;
      this.header = validated.header;
      this.samples = validated.samples;
      this.ringBufferByteLength = validated.ringBuffer.byteLength;
      this.descriptorValidated = true;
      if (!this.verifyMemoryIdentity()) {
        return false;
      }
      this.maybeReadyForClick();
      return true;
    } catch (error) {
      this.setFailure(fixedFailureCode(error));
      return false;
    }
  }

  reportProducerStarted() {
    if (!this.verifyMemoryIdentity() || this.failureCode !== null ||
        !this.startRequested ||
        !this.workletReady || this.producerStarted || this.header === null) {
      this.setFailure("producer-report-invalid");
      return false;
    }
    this.producerStarted = true;
    return true;
  }

  reportProducerFinished(totalFrames) {
    if (!this.verifyMemoryIdentity() || this.failureCode !== null ||
        !this.producerStarted ||
        this.producerFinished || totalFrames !== TOTAL_FRAMES ||
        this.header === null) {
      this.setFailure("producer-report-invalid");
      return false;
    }
    this.producerFinished = true;
    return true;
  }

  observeNativeOutput(line) {
    if (!this.verifyMemoryIdentity()) {
      return;
    }
    if (typeof line !== "string") {
      this.setFailure("native-output-invalid");
      return;
    }
    if (line === READY_MARKER) {
      if (this.nativeReady || this.nativeProducerStartedMarker ||
          this.nativeProducerDoneMarker) {
        this.setFailure("native-output-invalid");
        return;
      }
      this.nativeReady = true;
      this.maybeReadyForClick();
      return;
    }
    if (line === PRODUCER_STARTED_MARKER) {
      if (!this.nativeReady || this.nativeProducerStartedMarker ||
          this.nativeProducerDoneMarker) {
        this.setFailure("native-output-invalid");
      } else {
        this.nativeProducerStartedMarker = true;
        this.maybeResolveNativeProducerMarkers();
      }
      return;
    }
    if (line === PRODUCER_DONE_MARKER) {
      if (!this.nativeReady || !this.nativeProducerStartedMarker ||
          this.nativeProducerDoneMarker) {
        this.setFailure("native-output-invalid");
      } else {
        this.nativeProducerDoneMarker = true;
        this.maybeResolveNativeProducerMarkers();
      }
      return;
    }
    // Never preserve arbitrary Emscripten or browser output. A malformed
    // target-local marker is a safe failure category; unrelated output is
    // discarded without becoming result data or browser-console text.
    if (line.startsWith(NATIVE_PREFIX)) {
      this.setFailure("native-output-invalid");
    }
  }

  maybeResolveNativeProducerMarkers() {
    if (this.nativeProducerStartedMarker && this.nativeProducerDoneMarker) {
      this.nativeProducerMarkersSignal.resolve();
    }
  }

  maybeReadyForClick() {
    if (this.failureCode !== null || this.readyPosted ||
        !this.factorySettled || !this.runtimeInitialized ||
        !this.descriptorValidated || !this.nativeReady) {
      return;
    }
    if (!this.verifyMemoryIdentity()) {
      return;
    }
    this.startButton.disabled = false;
    setDocumentState("awaiting-trusted-click");
    this.readyForClick.resolve();
  }

  onStartClick(event) {
    if (this.failureCode !== null || this.finished || this.startRequested ||
        this.startButton.disabled || event.isTrusted !== true) {
      this.setFailure("trusted-gesture-invalid");
      return;
    }
    if (!this.verifyMemoryIdentity()) {
      return;
    }
    this.trustedGesture = true;
    this.startButton.disabled = true;
    setDocumentState("starting-audio");
    try {
      const context = new AudioContext({latencyHint: "interactive"});
      this.audioContext = context;
      // This call is intentionally synchronous in the trusted event handler.
      // The asynchronous worklet module/node work below is never used as a
      // substitute for the browser activation that initiates resume().
      const resumePromise = context.resume();
      this.resumeRequestedInTrustedGesture = true;
      void this.finishTrustedStart(context, resumePromise);
    } catch (_error) {
      this.setFailure("audio-context-create-failed");
    }
  }

  async finishTrustedStart(context, resumePromise) {
    try {
      await awaitBeforeDeadline(resumePromise, this.deadline,
                                "audio-context-not-running");
      if (context.state !== "running") {
        fail("audio-context-not-running");
      }
      this.audioContextRunning = true;
      if (!this.verifyMemoryIdentity() || this.ringBuffer === null ||
          this.header === null || this.samples === null) {
        fail("memory-growth-rejected");
      }
      const workletUrl = new URL("./m8_webaudio_ring_worklet.js", location.href);
      if (workletUrl.origin !== location.origin) {
        fail("worklet-add-module-failed");
      }
      await awaitBeforeDeadline(context.audioWorklet.addModule(workletUrl.href),
                                this.deadline, "worklet-add-module-failed");
      if (!this.verifyMemoryIdentity() || this.ringBuffer === null ||
          this.header === null || this.samples === null) {
        fail("memory-growth-rejected");
      }
      let node;
      try {
        node = new AudioWorkletNode(context, "chromium-wasm-m8-webaudio-ring", {
          channelCount: CHANNELS,
          channelCountMode: "explicit",
          numberOfInputs: 0,
          numberOfOutputs: 1,
          outputChannelCount: [CHANNELS],
          processorOptions: {
            protocol: DESCRIPTOR_PROTOCOL,
            ringBuffer: this.ringBuffer,
            headerByteOffset: this.header.byteOffset,
            samplesByteOffset: this.samples.byteOffset,
            capacityFrames: CAPACITY_FRAMES,
            channels: CHANNELS,
            totalFrames: TOTAL_FRAMES,
          },
        });
      } catch (_error) {
        fail("worklet-node-create-failed");
      }
      this.workletNode = node;
      node.port.onmessage = (event) => this.onWorkletMessage(event.data);
      node.onprocessorerror = () => this.setFailure("worklet-runtime-failed");
      node.connect(context.destination);
      await this.awaitSignalOrFailure(this.workletReadySignal.promise,
                                      "worklet-drain-timeout");
      if (!this.verifyMemoryIdentity() || this.header === null ||
          this.failureCode !== null) {
        fail("memory-growth-rejected");
      }
      this.startRequested = true;
      Atomics.store(this.header, START_REQUESTED, 1);
      setDocumentState("streaming");
      await this.awaitSignalOrFailure(this.workletDrainSignal.promise,
                                      "worklet-drain-timeout");
      // Pthread stdout delivery and AudioWorklet messages have separate async
      // paths. Do not assume a task turn orders them: admit success only after
      // both fixed native markers have converged before the run deadline.
      await this.awaitSignalOrFailure(this.nativeProducerMarkersSignal.promise,
                                      "native-marker-timeout");
      if (!this.producerStarted || !this.producerFinished ||
          !this.nativeProducerStartedMarker || !this.nativeProducerDoneMarker ||
          !this.verifyMemoryIdentity() ||
          this.header === null ||
          Atomics.load(this.header, WRITE_FRAME) !== TOTAL_FRAMES ||
          Atomics.load(this.header, READ_FRAME) !== TOTAL_FRAMES ||
          Atomics.load(this.header, PRODUCED_FRAMES) !== TOTAL_FRAMES ||
          Atomics.load(this.header, CONSUMED_FRAMES) !== TOTAL_FRAMES ||
          Atomics.load(this.header, PRODUCER_DONE) !== 1 ||
          Atomics.load(this.header, PRODUCER_STARTED) !== 1 ||
          Atomics.load(this.header, PRODUCER_ERROR) !== 0 ||
          this.workletUnderrunFrames !== Atomics.load(this.header, UNDERRUN_FRAMES)) {
        fail("worklet-drain-invalid");
      }
      this.setSuccess();
    } catch (error) {
      this.setFailure(fixedFailureCode(error));
    }
  }

  async awaitSignalOrFailure(signal, timeoutCode) {
    const outcome = await awaitBeforeDeadline(Promise.race([
      Promise.resolve(signal).then(() => "signal"),
      this.completion.promise.then(() => "completion"),
    ]), this.deadline, timeoutCode);
    if (outcome !== "signal" || this.failureCode !== null) {
      fail(this.failureCode || timeoutCode);
    }
  }

  onWorkletMessage(message) {
    if (!this.verifyMemoryIdentity()) {
      return;
    }
    if (exactWorkletReady(message)) {
      if (this.workletReady || this.failureCode !== null) {
        this.setFailure("worklet-protocol-invalid");
      } else {
        this.workletReady = true;
        this.workletReadySignal.resolve();
      }
      return;
    }
    if (validWorkletProgress(message)) {
      if (this.workletDrained || this.failureCode !== null) {
        this.setFailure("worklet-protocol-invalid");
      } else {
        this.workletProgressObserved = true;
      }
      return;
    }
    if (validWorkletDrained(message)) {
      if (this.workletDrained || this.failureCode !== null) {
        this.setFailure("worklet-protocol-invalid");
      } else {
        this.workletDrained = true;
        this.workletUnderrunFrames = message.underrunFrames;
        this.workletDrainSignal.resolve();
      }
      return;
    }
    if (exactWorkletError(message)) {
      this.setFailure("worklet-runtime-failed");
      return;
    }
    this.setFailure("worklet-protocol-invalid");
  }

  async loadRuntime() {
    if (!documentPrerequisites()) {
      fail("document-prerequisite");
    }
    setDocumentState("awaiting-ring");
    this.wasmMemory = createWasmMemory();
    this.startMemoryWatchdog();
    if (!this.verifyMemoryIdentity()) {
      fail("memory-growth-rejected");
    }
    globalThis[HOST_BRIDGE_NAME] = this.bridge;
    let loader;
    try {
      const moduleUrl = new URL("./artifacts/" + MODULE_NAME + ".js", location.href);
      if (moduleUrl.origin !== location.origin) {
        fail("module-loader-failed");
      }
      const response = await awaitBeforeDeadline(fetch(moduleUrl.href, {
        cache: "no-store",
        credentials: "same-origin",
      }), this.deadline, "module-loader-failed");
      if (!response.ok) {
        fail("module-loader-failed");
      }
      const mainScriptUrlOrBlob = await awaitBeforeDeadline(
          response.blob(), this.deadline, "module-loader-failed");
      if (mainScriptUrlOrBlob.size === 0) {
        fail("module-loader-failed");
      }
      const namespace = await awaitBeforeDeadline(
          import(moduleUrl.href), this.deadline, "module-loader-failed");
      if (typeof namespace.default !== "function") {
        fail("module-loader-failed");
      }
      loader = {moduleUrl, mainScriptUrlOrBlob, namespace};
    } catch (error) {
      fail(fixedFailureCode(error) === "host-exception" ?
          "module-loader-failed" : fixedFailureCode(error));
    }
    try {
      const factory = loader.namespace.default({
        noExitRuntime: true,
        wasmMemory: this.wasmMemory,
        mainScriptUrlOrBlob: loader.mainScriptUrlOrBlob,
        locateFile: (path) => new URL(path, loader.moduleUrl).href,
        print: (line) => this.observeNativeOutput(line),
        printErr: (line) => this.observeNativeOutput(line),
        onRuntimeInitialized: () => {
          this.runtimeInitialized = true;
          this.maybeReadyForClick();
        },
        onAbort: () => {
          this.runtimeAborted = true;
          this.setFailure("native-runtime-abort");
        },
        onExit: () => {
          this.runtimeExited = true;
          this.setFailure("native-runtime-exited");
        },
      });
      Promise.resolve(factory).then(
          (module) => {
            if (!module || (typeof module !== "object" &&
                            typeof module !== "function")) {
              this.setFailure("factory-failed");
              return;
            }
            this.factorySettled = true;
            this.maybeReadyForClick();
          },
          () => this.setFailure("factory-failed"));
    } catch (_error) {
      this.setFailure("factory-failed");
    }
  }

  async post(endpointName, value) {
    const endpoint = new URL("./" + endpointName + "/" +
                             encodeURIComponent(this.context.token), location.href);
    if (endpoint.origin !== location.origin) {
      fail("result-post-failed");
    }
    const response = await awaitBeforeDeadline(fetch(endpoint.href, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(value),
    }), this.deadline, "result-post-failed");
    if (response.status !== 204) {
      fail("result-post-failed");
    }
  }

  async postReady() {
    await this.post("ready", {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      ready: true,
    });
    this.readyPosted = true;
  }

  makeResult() {
    const passed = this.failureCode === null && this.finished &&
        this.trustedGesture && this.resumeRequestedInTrustedGesture &&
        this.audioContextRunning && this.descriptorValidated &&
        this.workletReady && this.workletDrained && this.producerStarted &&
        this.producerFinished && this.cleanupComplete && this.nodeDisconnected &&
        this.audioContextClosed && !this.memoryGrowthRejected &&
        this.memoryIdentityStable && this.memoryIdentityChecks > 0 &&
        !this.runtimeAborted && !this.runtimeExited;
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status: passed ? "pass" : "fail",
      failureCode: passed ? null : (this.failureCode || "host-exception"),
      secureContext: globalThis.isSecureContext === true,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      descriptorProtocol: DESCRIPTOR_PROTOCOL,
      channels: CHANNELS,
      totalFrames: TOTAL_FRAMES,
      descriptorValidated: this.descriptorValidated,
      memoryGrowthPolicy: "reject-on-any-memory-growth",
      memoryGrowthSignals: this.memoryGrowthSignals,
      memoryGrowthRejected: this.memoryGrowthRejected,
      memoryIdentityChecks: this.memoryIdentityChecks,
      memoryIdentityStable: this.memoryIdentityStable,
      nativeReady: this.nativeReady,
      nativeProducerStartedMarker: this.nativeProducerStartedMarker,
      nativeProducerDoneMarker: this.nativeProducerDoneMarker,
      runtimeInitialized: this.runtimeInitialized,
      runtimeFactorySettled: this.factorySettled,
      runtimeAborted: this.runtimeAborted,
      runtimeExited: this.runtimeExited,
      trustedGesture: this.trustedGesture,
      resumeRequestedInTrustedGesture: this.resumeRequestedInTrustedGesture,
      audioContextRunning: this.audioContextRunning,
      workletReady: this.workletReady,
      workletProgressObserved: this.workletProgressObserved,
      workletDrained: this.workletDrained,
      workletUnderrunFrames: this.workletUnderrunFrames,
      producerStarted: this.producerStarted,
      producerFinished: this.producerFinished,
      startRequested: this.startRequested,
      workletStopRequested: this.workletStopRequested,
      nodeDisconnected: this.nodeDisconnected,
      audioContextClosed: this.audioContextClosed,
      cleanupComplete: this.cleanupComplete,
      m8GateComplete: false,
      chromiumAudioManagerIntegrated: false,
      chromiumAudioServiceIntegrated: false,
      chromiumMediaSchedulingPreserved: false,
      muteVolumeDevicePolicyProven: false,
      tabSwitchingProven: false,
      browserMediaPlaybackProven: false,
      normalRuntimeShutdownProven: false,
    };
  }

  async cleanup() {
    this.startButton.disabled = true;
    this.stopWorkletNow();
    if (this.audioContext !== null) {
      try {
        await awaitBeforeDeadline(this.audioContext.close(),
                                  performance.now() + CLEANUP_TIMEOUT_MS,
                                  "audio-context-close-failed");
        this.audioContextClosed = this.audioContext.state === "closed";
        if (!this.audioContextClosed && this.failureCode === null) {
          this.setFailure("audio-context-close-failed");
        }
      } catch (_error) {
        if (this.failureCode === null) {
          this.setFailure("audio-context-close-failed");
        }
      }
    }
    this.clearRingViews();
    this.stopMemoryWatchdog();
    this.wasmMemory = null;
    if (globalThis[HOST_BRIDGE_NAME] === this.bridge) {
      delete globalThis[HOST_BRIDGE_NAME];
    }
    this.cleanupComplete = true;
  }

  async run() {
    try {
      await awaitBeforeDeadline(this.loadRuntime(), this.deadline,
                                "runtime-startup-timeout");
      const readyOrCompletion = await awaitBeforeDeadline(Promise.race([
        this.readyForClick.promise.then(() => "ready"),
        this.completion.promise.then(() => "completion"),
      ]), this.deadline, "runtime-startup-timeout");
      if (readyOrCompletion === "ready" && this.failureCode === null) {
        await this.postReady();
        const completed = await awaitBeforeDeadline(this.completion.promise,
                                                    this.deadline,
                                                    "worklet-drain-timeout");
        if (completed !== true && this.failureCode === null) {
          this.setFailure("host-exception");
        }
      }
    } catch (error) {
      this.setFailure(fixedFailureCode(error));
    }
    await this.cleanup();
    const result = this.makeResult();
    try {
      await this.post("result", result);
    } catch (_error) {
      setDocumentState("fail");
      return result;
    }
    setDocumentState(result.status === "pass" ? "pass" : "fail");
    return result;
  }
}

export async function runM8WebAudioRingSmokeFromQuery() {
  const context = parseM8WebAudioRingContext(location.search);
  const smoke = new M8WebAudioRingSmoke(context);
  return smoke.run();
}

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Host coordinator for one real media::AudioManager low-latency output stream.
// The versioned link-time library owns the native imports; this page only owns
// the WebAudio graph after a trusted user gesture and never calls a Wasm
// export. Descriptor pointers, samples, arbitrary native output, and thrown
// values remain local to this document.

export const HOST_PROTOCOL = 1;
export const DESCRIPTOR_PROTOCOL = 1;
export const CASE = "m8_audio_manager_output";
export const SCOPE =
    "one-default-low-latency-media-audiomanager-output-stream-to-trusted-webaudio-audioworklet";
export const DEFAULT_MODULE_NAME = "wasm_audio_manager_output_smoke";
export const HEADER_WORDS = 16;
export const HEADER_BYTES = HEADER_WORDS * Uint32Array.BYTES_PER_ELEMENT;
export const CAPACITY_FRAMES = 4096;
export const CHANNELS = 2;
export const SAMPLE_RATE = 48000;
export const FRAMES_PER_BUFFER = 480;
export const TOTAL_FRAMES = 12000;
export const START_BUTTON_X = 120;
export const START_BUTTON_Y = 48;

const HOST_BRIDGE_NAME = "__chromiumWasmAudioHostV1";
const MARKER_PREFIX = "CHROMIUM_WASM_M8_AUDIO_MANAGER:";
const EXPECTED_MARKERS = Object.freeze([
  `${MARKER_PREFIX}READY`,
  `${MARKER_PREFIX}OPENED`,
  `${MARKER_PREFIX}STARTED`,
  `${MARKER_PREFIX}DRAINED`,
  `${MARKER_PREFIX}STOPPED`,
  `${MARKER_PREFIX}CLOSED`,
]);
const FAILURE_STAGES = new Set([
  "pthread",
  "manager",
  "open",
  "start",
  "drain",
  "stop",
  "shutdown",
]);
const FAILURE_CODES = new Set([
  "audio-context-close-failed",
  "audio-context-create-failed",
  "audio-context-not-running",
  "audio-context-sample-rate-invalid",
  "bridge-install-failed",
  "cleanup-invalid",
  "descriptor-duplicate",
  "descriptor-invalid",
  "descriptor-unregister-invalid",
  "document-prerequisite",
  "factory-failed",
  "host-exception",
  "marker-before-arm",
  "marker-inactive",
  "marker-native-failure",
  "marker-outside-stderr",
  "marker-unexpected",
  "memory-identity-invalid",
  "module-loader-failed",
  "native-runtime-abort",
  "native-runtime-exit-invalid",
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
const FATAL_TAGS = new Set([
  "audio-context-close-failed",
  "audio-context-create-failed",
  "audio-context-not-running",
  "audio-context-sample-rate-invalid",
  "bridge-install-failed",
  "cleanup-invalid",
  "descriptor-duplicate",
  "descriptor-invalid",
  "descriptor-unregister-invalid",
  "document-prerequisite",
  "factory-failed",
  "host-exception",
  "marker-before-arm",
  "marker-inactive",
  "marker-native-failure",
  "marker-outside-stderr",
  "marker-unexpected",
  "memory-identity-invalid",
  "native-runtime-abort",
  "native-runtime-exit-invalid",
  "runtime-startup-timeout",
  "trusted-gesture-invalid",
  "worklet-drain-invalid",
  "worklet-protocol-invalid",
]);
const FAILURE_CLASSES = new Set([
  "host-exception",
  "host-lifecycle",
  "host-timeout",
  "native-fixed-failure",
  "opaque-output-suppressed",
]);
const HOST_STATE_REGISTERED = 0;
const HOST_STATE_STARTED = 1;
const HOST_STATE_DRAINED = 2;
const HOST_STATE_STOPPED = 3;
const HOST_STATE_ERROR = 0xffffffff;
const PRODUCER_IDLE = 0;
const PRODUCER_STARTED = 1;
const PRODUCER_STOPPED = 2;
const PRODUCER_ERROR_NONE = 0;
const MAX_UINT32 = 0xffffffff;
const MAX_TIMEOUT_MS = 120000;
const MIN_TIMEOUT_MS = 1000;
const CLEANUP_TIMEOUT_MS = 2500;
const FINAL_QUIESCENCE_MS = 50;
const MEMORY_WATCHDOG_MS = 25;
const MAX_COUNTER = 1 << 24;
const MAX_UNDERRUN_FRAMES = 1 << 22;
const WASM_PAGE_BYTES = 64 * 1024;
const WASM_INITIAL_PAGES = 1024;
const WASM_MAXIMUM_PAGES = 32768;
const WASM_INITIAL_BYTES = WASM_PAGE_BYTES * WASM_INITIAL_PAGES;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
const MODULE_RE = /^[A-Za-z0-9_]+$/;
const REVISION_RE = /^[0-9a-f]{40}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;

const ARTIFACT_FIELDS = Object.freeze([
  "artifactDelivery",
  "artifactSourceProvenance",
  "buildConfig",
  "buildConfigProvenance",
  "loader",
  "moduleName",
  "wasm",
]);
const CAPTURE_HARNESS_FIELDS = Object.freeze([
  "bridgeLibrary",
  "hostHtml",
  "hostJs",
  "runnerSource",
  "sourceSnapshotProvenance",
  "versionProvenance",
  "workletJs",
]);
const SUCCESS_FIELDS = Object.freeze([
  "artifact",
  "audioContextClosed",
  "audioContextRunning",
  "audioManagerOutputPathProven",
  "audioServiceIntegrated",
  "browserMediaPlaybackProven",
  "capacityFrames",
  "case",
  "captureHarness",
  "channels",
  "cleanupComplete",
  "consumedFrames",
  "crossOriginIsolated",
  "descriptorGeneration",
  "descriptorProtocol",
  "descriptorRegistered",
  "descriptorRegistrationCount",
  "descriptorValidated",
  "deviceChangePolicyProven",
  "failureCode",
  "fixedGainPathProven",
  "framesPerBuffer",
  "hostState",
  "inputProven",
  "limitations",
  "m8GateComplete",
  "memoryIdentityChecks",
  "memoryIdentityStable",
  "mutePolicyProven",
  "nativeMarkerSequenceAccepted",
  "nativeMarkerSource",
  "nativeMarkers",
  "normalModuleExitObserved",
  "normalRuntimeShutdownProven",
  "onExitCount",
  "origin",
  "outputArmed",
  "producerError",
  "producedFrames",
  "protocol",
  "resumeRequestedInTrustedGesture",
  "runtimeAborted",
  "runtimeExitCode",
  "runtimeFactorySettled",
  "runtimeInitialized",
  "sampleRate",
  "sameOriginDocument",
  "scope",
  "secureContext",
  "sharedArrayBuffer",
  "startObserved",
  "status",
  "stopObserved",
  "tabSwitchingProven",
  "totalFrames",
  "trustedGesture",
  "underrunFrames",
  "unregisterObserved",
  "versions",
  "workletDisconnected",
  "workletDrained",
  "workletFramesRead",
  "workletNonSilentFrames",
  "workletProgressObserved",
  "workletReady",
  "workletStopRequested",
]);
const FAILURE_FIELDS = Object.freeze([
  "case",
  "failureClass",
  "firstFatalTag",
  "lifecycle",
  "nativeFailureStage",
  "protocol",
  "scope",
  "status",
]);
const FAILURE_LIFECYCLE_FIELDS = Object.freeze([
  "cleanupComplete",
  "descriptorRegistered",
  "factorySettled",
  "markerCount",
  "normalExitObserved",
  "outputArmed",
  "runtimeInitialized",
  "unregisterObserved",
  "workletDrained",
  "workletReady",
]);
const LIMITATIONS = Object.freeze([
  "proves_only_one_default_low_latency_media_audiomanager_output_stream",
  "proves_only_fixed_0_5_per_stream_gain_for_this_smoke",
  "does_not_prove_audio_service_or_audio_input",
  "does_not_prove_device_change_mute_or_tab_switching_policy",
  "does_not_prove_dynamic_volume_changes_or_multi_stream_gain_mixing",
  "does_not_prove_browser_media_playback_or_global_scheduling",
  "does_not_prove_start_stop_start_or_stream_reuse",
  "does_not_serialize_raw_native_output_exceptions_or_sab_addresses",
  "does_not_claim_m8_2_audio_gate_or_m8_complete_or_normal_outer_browser_shutdown",
]);

class AudioOutputHostError extends Error {
  constructor(code) {
    super(code);
    this.code = FAILURE_CODES.has(code) ? code : "host-exception";
  }
}

function fail(code) {
  throw new AudioOutputHostError(code);
}

function fixedFailureCode(error) {
  return error instanceof AudioOutputHostError ? error.code : "host-exception";
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

function exactJsonEqual(left, right) {
  if (typeof left !== typeof right || left === null || right === null) {
    return left === right;
  }
  if (Array.isArray(left)) {
    return Array.isArray(right) && left.length === right.length &&
        left.every((value, index) => exactJsonEqual(value, right[index]));
  }
  if (typeof left === "object") {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return leftKeys.length === rightKeys.length &&
        leftKeys.every((key, index) => key === rightKeys[index] &&
            exactJsonEqual(left[key], right[key]));
  }
  return left === right;
}

function isUint32(value) {
  return Number.isSafeInteger(value) && value >= 0 && value <= MAX_UINT32;
}

function isBoundedCount(value, maximum = MAX_COUNTER) {
  return Number.isSafeInteger(value) && value >= 0 && value <= maximum;
}

function asPositiveUint32(value) {
  return isUint32(value) && value !== 0;
}

function parseJsonObject(value, code) {
  try {
    const parsed = JSON.parse(value);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed) ||
        Object.getPrototypeOf(parsed) !== Object.prototype) {
      fail(code);
    }
    return parsed;
  } catch (_error) {
    fail(code);
  }
}

function validateByteIdentity(value, code) {
  if (!hasExactKeys(value, ["bytes", "sha256"]) ||
      !Number.isSafeInteger(value.bytes) || value.bytes < 1 ||
      typeof value.sha256 !== "string" || !SHA256_RE.test(value.sha256)) {
    fail(code);
  }
  return Object.freeze({bytes: value.bytes, sha256: value.sha256});
}

function validateArtifact(value, moduleName, code) {
  if (!hasExactKeys(value, ARTIFACT_FIELDS) ||
      value.artifactDelivery !== "immutable-in-memory-server-snapshot" ||
      value.artifactSourceProvenance !== "unverified" ||
      value.buildConfigProvenance !==
          "selected-out-dir-args-gn-immutable-snapshot" ||
      value.moduleName !== moduleName) {
    fail(code);
  }
  return Object.freeze({
    artifactDelivery: value.artifactDelivery,
    artifactSourceProvenance: value.artifactSourceProvenance,
    buildConfig: validateByteIdentity(value.buildConfig, code),
    buildConfigProvenance: value.buildConfigProvenance,
    loader: validateByteIdentity(value.loader, code),
    moduleName: value.moduleName,
    wasm: validateByteIdentity(value.wasm, code),
  });
}

function validateCaptureHarness(value, code) {
  if (!hasExactKeys(value, CAPTURE_HARNESS_FIELDS) ||
      value.sourceSnapshotProvenance !==
          "on-disk-byte-snapshots-at-server-startup-not-commit-provenance" ||
      value.versionProvenance !==
          "toolchain-manifest-metadata-only-not-artifact-or-harness-source-provenance") {
    fail(code);
  }
  return Object.freeze({
    bridgeLibrary: validateByteIdentity(value.bridgeLibrary, code),
    hostHtml: validateByteIdentity(value.hostHtml, code),
    hostJs: validateByteIdentity(value.hostJs, code),
    runnerSource: validateByteIdentity(value.runnerSource, code),
    sourceSnapshotProvenance: value.sourceSnapshotProvenance,
    versionProvenance: value.versionProvenance,
    workletJs: validateByteIdentity(value.workletJs, code),
  });
}

function validateVersions(value, code) {
  if (!hasExactKeys(value, ["chromium", "emscripten", "v8"]) ||
      !Object.values(value).every((entry) =>
        typeof entry === "string" && REVISION_RE.test(entry))) {
    fail(code);
  }
  return Object.freeze({
    chromium: value.chromium,
    emscripten: value.emscripten,
    v8: value.v8,
  });
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
  const timeoutMs = Number(value);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < MIN_TIMEOUT_MS ||
      timeoutMs > MAX_TIMEOUT_MS) {
    fail("document-prerequisite");
  }
  return timeoutMs;
}

export function parseM8AudioManagerOutputContext(search) {
  const query = new URLSearchParams(search);
  const allowed = new Set([
    "artifact", "captureHarness", "module", "timeoutMs", "token", "versions",
  ]);
  for (const name of query.keys()) {
    if (!allowed.has(name)) {
      fail("document-prerequisite");
    }
  }
  const token = oneQueryValue(query, "token");
  const moduleName = oneQueryValue(query, "module");
  if (!TOKEN_RE.test(token) || !MODULE_RE.test(moduleName)) {
    fail("document-prerequisite");
  }
  const context = {
    token,
    moduleName,
    timeoutMs: parseTimeout(oneQueryValue(query, "timeoutMs")),
    versions: validateVersions(
        parseJsonObject(oneQueryValue(query, "versions"), "document-prerequisite"),
        "document-prerequisite"),
    artifact: validateArtifact(
        parseJsonObject(oneQueryValue(query, "artifact"), "document-prerequisite"),
        moduleName, "document-prerequisite"),
    captureHarness: validateCaptureHarness(
        parseJsonObject(oneQueryValue(query, "captureHarness"),
                        "document-prerequisite"),
        "document-prerequisite"),
  };
  return Object.freeze(context);
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

function makeDeferred() {
  let resolve;
  const promise = new Promise((resolver) => { resolve = resolver; });
  return {promise, resolve};
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
    timer = setTimeout(() => reject(new AudioOutputHostError(code)), remaining);
  });
  try {
    return await Promise.race([Promise.resolve(promise), timeout]);
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
  }
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
  } catch (_error) {
    fail("wasm-memory-create-failed");
  }
}

function getElement(selector, type) {
  const element = document.querySelector(selector);
  if (!(element instanceof type)) {
    fail("document-prerequisite");
  }
  return element;
}

function setDocumentState(state) {
  const root = document.querySelector("#m8-audio-manager-output-root");
  const status = document.querySelector("#m8-audio-manager-output-status");
  if (root instanceof HTMLElement) {
    root.dataset.state = state;
  }
  if (status instanceof HTMLElement) {
    const fixedStatus = {
      "awaiting-native": "Waiting for the AudioManager output stream…",
      "awaiting-trusted-click": "Ready for a trusted Start audio output click.",
      "arming-output": "Resuming WebAudio for the native output stream…",
      "streaming": "Draining the native AudioManager output ring…",
      "pass": "AudioManager output smoke passed.",
      "fail": "AudioManager output smoke failed.",
    };
    status.textContent = fixedStatus[state] || "AudioManager output smoke.";
  }
}

function fixedNativeFailureStage(line) {
  if (!line.startsWith(MARKER_PREFIX)) {
    return null;
  }
  const match = /^CHROMIUM_WASM_M8_AUDIO_MANAGER:FAIL stage=([a-z-]+)$/.exec(line);
  return match !== null && FAILURE_STAGES.has(match[1]) ? match[1] : null;
}

function nativeMarkerIndex(line) {
  return EXPECTED_MARKERS.indexOf(line);
}

function markerName(index) {
  return EXPECTED_MARKERS[index].slice(MARKER_PREFIX.length);
}

function exactWorkletReady(message) {
  return hasExactKeys(message, ["protocol", "type"]) &&
      message.protocol === DESCRIPTOR_PROTOCOL && message.type === "ready";
}

function exactWorkletError(message) {
  return hasExactKeys(message, ["code", "protocol", "type"]) &&
      message.protocol === DESCRIPTOR_PROTOCOL && message.type === "error" &&
      new Set([
        "fixed-gain-invalid", "header-invalid", "output-invalid", "producer-error",
        "processor-error", "worklet-message-invalid",
      ]).has(message.code);
}

function validWorkletProgress(message) {
  return hasExactKeys(message, [
    "consumedFrames", "framesRead", "nonSilentFrames", "processCalls",
    "protocol", "readIndex", "type", "underrunFrames", "writeIndex",
  ]) && message.protocol === DESCRIPTOR_PROTOCOL && message.type === "progress" &&
      ["consumedFrames", "framesRead", "nonSilentFrames", "readIndex",
       "underrunFrames", "writeIndex"].every((field) =>
        isUint32(message[field])) && isBoundedCount(message.processCalls);
}

function validWorkletDrained(message) {
  return hasExactKeys(message, [
    "consumedFrames", "fixedGainPathProven", "framesRead", "nonSilentFrames",
    "processCalls", "producedFrames", "protocol", "readIndex", "type",
    "underrunFrames", "writeIndex",
  ]) && message.protocol === DESCRIPTOR_PROTOCOL && message.type === "drained" &&
      ["consumedFrames", "framesRead", "nonSilentFrames", "producedFrames",
       "readIndex", "underrunFrames", "writeIndex"].every(
          (field) => isUint32(message[field])) &&
      isBoundedCount(message.processCalls) && message.fixedGainPathProven === true;
}

function isExactNormalEmscriptenExitStatus(value) {
  return value !== null && typeof value === "object" &&
      Object.getPrototypeOf(value) === Object.prototype &&
      hasExactKeys(value, ["message", "name", "status"]) &&
      value.name === "ExitStatus" && value.status === 0 &&
      value.message === "Program terminated with exit(0)";
}

function validateDescriptor(value, wasmMemory) {
  if (!hasExactKeys(value, [
    "capacityFrames", "channels", "framesPerBuffer", "generation",
    "headerByteOffset", "protocol", "ringBuffer", "sampleRate",
    "samplesByteOffset",
  ]) || value.protocol !== DESCRIPTOR_PROTOCOL ||
      value.capacityFrames !== CAPACITY_FRAMES || value.channels !== CHANNELS ||
      value.sampleRate !== SAMPLE_RATE || value.framesPerBuffer !== FRAMES_PER_BUFFER ||
      !asPositiveUint32(value.generation) ||
      !(value.ringBuffer instanceof SharedArrayBuffer) ||
      wasmMemory === null || value.ringBuffer !== wasmMemory.buffer ||
      value.ringBuffer.byteLength !== WASM_INITIAL_BYTES ||
      !isUint32(value.headerByteOffset) || !isUint32(value.samplesByteOffset) ||
      (value.headerByteOffset & 3) !== 0 || (value.samplesByteOffset & 3) !== 0) {
    fail("descriptor-invalid");
  }
  const sampleBytes = CAPACITY_FRAMES * CHANNELS * Float32Array.BYTES_PER_ELEMENT;
  const headerEnd = value.headerByteOffset + HEADER_BYTES;
  const samplesEnd = value.samplesByteOffset + sampleBytes;
  if (!Number.isSafeInteger(headerEnd) || !Number.isSafeInteger(samplesEnd) ||
      headerEnd < value.headerByteOffset || samplesEnd < value.samplesByteOffset ||
      headerEnd > value.ringBuffer.byteLength || samplesEnd > value.ringBuffer.byteLength ||
      (headerEnd > value.samplesByteOffset && samplesEnd > value.headerByteOffset)) {
    fail("descriptor-invalid");
  }
  const header = new Uint32Array(value.ringBuffer, value.headerByteOffset, HEADER_WORDS);
  const expected = [
    DESCRIPTOR_PROTOCOL, CAPACITY_FRAMES, CHANNELS, SAMPLE_RATE,
    FRAMES_PER_BUFFER, value.generation, PRODUCER_IDLE, 0, 0, 0, 0, 0,
    PRODUCER_ERROR_NONE, HOST_STATE_REGISTERED, 0, 0,
  ];
  if (expected.some((entry, index) => Atomics.load(header, index) !== entry)) {
    fail("descriptor-invalid");
  }
  return Object.freeze({
    generation: value.generation,
    header,
    headerByteOffset: value.headerByteOffset,
    ringBuffer: value.ringBuffer,
    samples: new Float32Array(value.ringBuffer, value.samplesByteOffset,
                              CAPACITY_FRAMES * CHANNELS),
    samplesByteOffset: value.samplesByteOffset,
  });
}

function headerSnapshot(header) {
  if (!(header instanceof Uint32Array) || header.length !== HEADER_WORDS) {
    return null;
  }
  const snapshot = [];
  for (let index = 0; index !== HEADER_WORDS; ++index) {
    const value = Atomics.load(header, index);
    if (!isUint32(value)) {
      return null;
    }
    snapshot.push(value);
  }
  return snapshot;
}

export class M8AudioManagerOutputSmoke {
  constructor(context) {
    this.context = context;
    this.deadline = deadlineAfter(context.timeoutMs);
    this.root = getElement("#m8-audio-manager-output-root", HTMLElement);
    this.startButton = getElement("#m8-audio-manager-output-start", HTMLButtonElement);
    this.startButton.disabled = true;
    this.startButton.addEventListener("click", (event) => this.onStartClick(event));

    this.factorySettled = false;
    this.runtimeInitialized = false;
    this.runtimeAborted = false;
    this.onExitCount = 0;
    this.runtimeExitCode = null;
    this.normalModuleExitObserved = false;
    this.module = null;
    this.wasmMemory = null;
    this.memoryWatchdog = null;
    this.memoryIdentityChecks = 0;
    this.memoryIdentityStable = false;
    this.descriptor = null;
    this.descriptorRegistered = false;
    this.descriptorRegistrationCount = 0;
    this.unregisterObserved = false;
    this.nativeMarkers = [];
    this.markerIndex = 0;
    this.nativeMarkerSequenceAccepted = true;
    this.nativeFailureStage = null;
    this.trustedGesture = false;
    this.resumeRequestedInTrustedGesture = false;
    this.audioContext = null;
    this.audioContextRunning = false;
    this.workletNode = null;
    this.workletReady = false;
    this.workletProgressObserved = false;
    this.workletDrained = false;
    this.workletFramesRead = 0;
    this.workletNonSilentFrames = 0;
    this.fixedGainPathProven = false;
    this.workletUnderrunFrames = 0;
    this.outputArmed = false;
    this.startObserved = false;
    this.stopObserved = false;
    this.workletStopRequested = false;
    this.workletDisconnected = false;
    this.audioContextClosed = false;
    this.cleanupComplete = false;
    this.finalHeader = null;
    this.quiescenceScheduled = false;
    this.callbacksAtQuiescenceStart = null;
    this.nativeLifecycleComplete = false;
    this.callbackCount = 0;
    this.failureCode = null;
    this.firstFatalTag = null;
    this.readyPosted = false;
    this.finished = false;
    this.readySignal = makeDeferred();
    this.completion = makeDeferred();
    this.workletReadySignal = makeDeferred();
    this.bridge = Object.freeze({
      protocol: DESCRIPTOR_PROTOCOL,
      isOutputArmed: () => this.isOutputArmed(),
      registerOutputRing: (descriptor) => this.registerOutputRing(descriptor),
      unregisterOutputRing: (generation) => this.unregisterOutputRing(generation),
    });
  }

  noteCallback() {
    this.callbackCount += 1;
  }

  setFailure(code, tag = code) {
    const fixedCode = FAILURE_CODES.has(code) ? code : "host-exception";
    const fixedTag = FATAL_TAGS.has(tag) ? tag : "host-exception";
    if (this.failureCode !== null) {
      return;
    }
    this.failureCode = fixedCode;
    this.firstFatalTag = fixedTag;
    if (this.descriptor !== null) {
      try {
        Atomics.store(this.descriptor.header, 13, HOST_STATE_ERROR);
      } catch (_error) {
        // A malformed descriptor is already represented by the fixed failure.
      }
    }
    if (!this.finished) {
      this.finished = true;
      this.completion.resolve(false);
    }
  }

  isOutputArmed() {
    this.noteCallback();
    return this.failureCode === null && this.outputArmed === true &&
        this.audioContextRunning === true && this.workletReady === true;
  }

  verifyMemoryIdentity() {
    if (this.wasmMemory === null) {
      return false;
    }
    this.memoryIdentityChecks += 1;
    try {
      const buffer = this.wasmMemory.buffer;
      if (!(buffer instanceof SharedArrayBuffer) ||
          buffer.byteLength !== WASM_INITIAL_BYTES ||
          (this.descriptor !== null &&
           (buffer !== this.descriptor.ringBuffer ||
            buffer.byteLength !== this.descriptor.ringBuffer.byteLength))) {
        this.memoryIdentityStable = false;
        this.setFailure("memory-identity-invalid");
        return false;
      }
      this.memoryIdentityStable = true;
      return true;
    } catch (_error) {
      this.memoryIdentityStable = false;
      this.setFailure("memory-identity-invalid");
      return false;
    }
  }

  startMemoryWatchdog() {
    if (this.memoryWatchdog !== null) {
      this.setFailure("memory-identity-invalid");
      return;
    }
    this.memoryWatchdog = setInterval(() => this.verifyMemoryIdentity(),
                                      MEMORY_WATCHDOG_MS);
  }

  stopMemoryWatchdog() {
    if (this.memoryWatchdog !== null) {
      clearInterval(this.memoryWatchdog);
      this.memoryWatchdog = null;
    }
  }

  registerOutputRing(descriptor) {
    this.noteCallback();
    if (this.failureCode !== null || this.finished || this.descriptorRegistered ||
        this.descriptorRegistrationCount !== 0) {
      this.setFailure("descriptor-duplicate");
      return false;
    }
    try {
      const validated = validateDescriptor(descriptor, this.wasmMemory);
      if (!this.verifyMemoryIdentity()) {
        return false;
      }
      this.descriptor = validated;
      this.descriptorRegistered = true;
      this.descriptorRegistrationCount = 1;
      this.maybeReadyForClick();
      return true;
    } catch (error) {
      this.setFailure(fixedFailureCode(error), "descriptor-invalid");
      return false;
    }
  }

  unregisterOutputRing(generation) {
    this.noteCallback();
    if (this.failureCode !== null || !this.descriptorRegistered ||
        this.unregisterObserved || !isUint32(generation) ||
        this.descriptor === null || generation !== this.descriptor.generation ||
        // Native Stop has changed the unsigned producer state, but the
        // protocol's STOPPED marker follows this unregister callback.
        this.markerIndex !== 4) {
      this.setFailure("descriptor-unregister-invalid");
      return false;
    }
    const header = headerSnapshot(this.descriptor.header);
    if (header === null || header[6] !== PRODUCER_STOPPED ||
        header[12] !== PRODUCER_ERROR_NONE) {
      this.setFailure("descriptor-unregister-invalid");
      return false;
    }
    this.unregisterObserved = true;
    this.maybeCompleteNativeLifecycle();
    return true;
  }

  captureNativeOutput(destination, value) {
    this.noteCallback();
    const line = typeof value === "string" ? value : "<suppressed-nonstring>";
    const containsMarker = line.includes(MARKER_PREFIX);
    if (!containsMarker) {
      return;
    }
    if (destination !== "stderr") {
      this.setFailure("marker-outside-stderr");
      return;
    }
    if (this.failureCode !== null || this.nativeLifecycleComplete) {
      this.setFailure("marker-inactive");
      return;
    }
    const nativeFailureStage = fixedNativeFailureStage(line);
    if (nativeFailureStage !== null) {
      if (this.nativeFailureStage !== null || this.markerIndex !== 0) {
        this.setFailure("marker-unexpected");
        return;
      }
      this.nativeFailureStage = nativeFailureStage;
      this.setFailure("marker-native-failure");
      return;
    }
    const expected = EXPECTED_MARKERS[this.markerIndex] || null;
    if (line !== expected || nativeMarkerIndex(line) !== this.markerIndex) {
      this.nativeMarkerSequenceAccepted = false;
      this.setFailure("marker-unexpected");
      return;
    }
    if (this.markerIndex === 1 && !this.descriptorRegistered) {
      this.setFailure("descriptor-invalid");
      return;
    }
    if (this.markerIndex === 2 && !this.isOutputArmed()) {
      this.setFailure("marker-before-arm");
      return;
    }
    if (this.markerIndex === 3 && !this.hasDrainedHeader()) {
      this.setFailure("worklet-drain-invalid");
      return;
    }
    if (this.markerIndex === 4 && !this.hasStoppedHeader()) {
      this.setFailure("worklet-drain-invalid");
      return;
    }
    if (this.markerIndex === 5 && !this.unregisterObserved) {
      this.setFailure("descriptor-unregister-invalid");
      return;
    }
    this.nativeMarkers.push(line);
    this.markerIndex += 1;
    this.startObserved ||= markerName(this.markerIndex - 1) === "STARTED";
    this.stopObserved ||= markerName(this.markerIndex - 1) === "STOPPED";
    if (this.markerIndex === 3) {
      setDocumentState("streaming");
    }
    this.maybeReadyForClick();
    this.maybeCompleteNativeLifecycle();
  }

  onRuntimeInitialized() {
    this.noteCallback();
    if (this.runtimeInitialized) {
      this.setFailure("factory-failed");
      return;
    }
    this.runtimeInitialized = true;
    this.maybeReadyForClick();
  }

  onAbort() {
    this.noteCallback();
    this.runtimeAborted = true;
    this.setFailure("native-runtime-abort");
  }

  onExit(code) {
    this.noteCallback();
    this.onExitCount += 1;
    if (!Number.isInteger(code) || this.onExitCount !== 1 || code !== 0 ||
        this.markerIndex < 4 || !this.unregisterObserved ||
        !this.hasStoppedHeader()) {
      this.setFailure("native-runtime-exit-invalid");
      return;
    }
    // The native sequence emits STOPPED and CLOSED before returning. Pthread
    // stderr forwarding is separate from the Module.onExit callback, though,
    // so those two already-emitted markers may reach this host afterward.
    // Keep the normal exit pending until their exact ordered delivery is
    // observed; success still requires the complete six-marker sequence.
    this.runtimeExitCode = 0;
    this.normalModuleExitObserved = true;
    this.maybeCompleteNativeLifecycle();
  }

  onFactorySettled(module) {
    this.noteCallback();
    if (this.factorySettled || !module ||
        (typeof module !== "object" && typeof module !== "function")) {
      this.setFailure("factory-failed");
      return;
    }
    this.factorySettled = true;
    this.module = module;
    this.maybeReadyForClick();
    this.maybeCompleteNativeLifecycle();
  }

  onFactoryRejected(error) {
    this.noteCallback();
    if (this.factorySettled || !isExactNormalEmscriptenExitStatus(error)) {
      this.setFailure("factory-failed");
      return;
    }
    // A normal Emscripten ExitStatus can be delivered in a promise reaction
    // before its pthread-proxied onExit callback. Completion separately
    // requires exactly one onExit(0), the stopped/unregistered ring, and all
    // six fixed stderr markers.
    this.factorySettled = true;
    this.maybeReadyForClick();
    this.maybeCompleteNativeLifecycle();
  }

  maybeReadyForClick() {
    if (this.failureCode !== null || this.readyPosted || !this.runtimeInitialized ||
        !this.factorySettled || !this.descriptorRegistered ||
        this.markerIndex !== 2 || !this.verifyMemoryIdentity()) {
      return;
    }
    this.startButton.disabled = false;
    setDocumentState("awaiting-trusted-click");
    this.readySignal.resolve();
  }

  onStartClick(event) {
    this.noteCallback();
    if (this.failureCode !== null || this.outputArmed || this.startButton.disabled ||
        event.isTrusted !== true || this.markerIndex !== 2 ||
        !this.descriptorRegistered || !this.verifyMemoryIdentity()) {
      this.setFailure("trusted-gesture-invalid");
      return;
    }
    this.trustedGesture = true;
    this.startButton.disabled = true;
    setDocumentState("arming-output");
    try {
      const context = new AudioContext({
        latencyHint: "interactive",
        sampleRate: SAMPLE_RATE,
      });
      this.audioContext = context;
      // This must remain in the trusted click stack. The later async worklet
      // work cannot substitute for user activation.
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
      if (context.state !== "running" || context.sampleRate !== SAMPLE_RATE ||
          !this.verifyMemoryIdentity() ||
          this.descriptor === null) {
        fail(context.state !== "running" ? "audio-context-not-running" :
            "audio-context-sample-rate-invalid");
      }
      this.audioContextRunning = true;
      const workletUrl = new URL("./m8_audio_manager_output_worklet.js", location.href);
      if (workletUrl.origin !== location.origin) {
        fail("worklet-add-module-failed");
      }
      await awaitBeforeDeadline(context.audioWorklet.addModule(workletUrl.href),
                                this.deadline, "worklet-add-module-failed");
      if (!this.verifyMemoryIdentity() || this.descriptor === null) {
        fail("memory-identity-invalid");
      }
      let node;
      try {
        node = new AudioWorkletNode(context,
            "chromium-wasm-m8-audio-manager-output", {
              channelCount: CHANNELS,
              channelCountMode: "explicit",
              numberOfInputs: 0,
              numberOfOutputs: 1,
              outputChannelCount: [CHANNELS],
              processorOptions: {
                generation: this.descriptor.generation,
                headerByteOffset: this.descriptor.headerByteOffset,
                protocol: DESCRIPTOR_PROTOCOL,
                ringBuffer: this.descriptor.ringBuffer,
                samplesByteOffset: this.descriptor.samplesByteOffset,
              },
            });
      } catch (_error) {
        fail("worklet-node-create-failed");
      }
      this.workletNode = node;
      node.port.onmessage = (event) => this.onWorkletMessage(event.data);
      node.onprocessorerror = () => this.setFailure("worklet-runtime-failed");
      node.connect(context.destination);
      await awaitBeforeDeadline(this.workletReadySignal.promise, this.deadline,
                                "worklet-drain-timeout");
      if (this.failureCode !== null || this.descriptor === null ||
          !this.verifyMemoryIdentity()) {
        fail("memory-identity-invalid");
      }
      this.outputArmed = true;
      // Publish the post-click/worklet arm only after its boolean gate is
      // true, so native's ensuing synchronous isOutputArmed import cannot
      // observe a STARTED header state with a false arm.
      Atomics.store(this.descriptor.header, 13, HOST_STATE_STARTED);
    } catch (error) {
      this.setFailure(fixedFailureCode(error));
    }
  }

  onWorkletMessage(message) {
    this.noteCallback();
    if (this.failureCode !== null || !this.verifyMemoryIdentity()) {
      return;
    }
    if (exactWorkletReady(message)) {
      if (this.workletReady) {
        this.setFailure("worklet-protocol-invalid");
        return;
      }
      this.workletReady = true;
      this.workletReadySignal.resolve();
      return;
    }
    if (validWorkletProgress(message)) {
      if (this.workletDrained) {
        this.setFailure("worklet-protocol-invalid");
        return;
      }
      this.workletProgressObserved = true;
      this.workletFramesRead = message.framesRead;
      this.workletNonSilentFrames = message.nonSilentFrames;
      this.workletUnderrunFrames = message.underrunFrames;
      return;
    }
    if (validWorkletDrained(message)) {
      if (this.workletDrained || !this.hasDrainedHeader() ||
          message.readIndex !== message.writeIndex ||
          message.writeIndex !== message.producedFrames ||
          message.consumedFrames !== message.producedFrames ||
          message.producedFrames !== TOTAL_FRAMES ||
          message.framesRead !== TOTAL_FRAMES ||
          message.nonSilentFrames !== TOTAL_FRAMES ||
          message.fixedGainPathProven !== true) {
        this.setFailure("worklet-drain-invalid");
        return;
      }
      this.workletDrained = true;
      this.workletFramesRead = message.framesRead;
      this.workletNonSilentFrames = message.nonSilentFrames;
      this.fixedGainPathProven = message.fixedGainPathProven;
      this.workletUnderrunFrames = message.underrunFrames;
      this.maybeCompleteNativeLifecycle();
      return;
    }
    if (exactWorkletError(message)) {
      this.setFailure("worklet-runtime-failed");
      return;
    }
    this.setFailure("worklet-protocol-invalid");
  }

  currentHeader() {
    if (this.descriptor === null) {
      return null;
    }
    const snapshot = headerSnapshot(this.descriptor.header);
    if (snapshot === null || snapshot[0] !== DESCRIPTOR_PROTOCOL ||
        snapshot[1] !== CAPACITY_FRAMES || snapshot[2] !== CHANNELS ||
        snapshot[3] !== SAMPLE_RATE || snapshot[4] !== FRAMES_PER_BUFFER ||
        snapshot[5] !== this.descriptor.generation || snapshot[14] !== 0 ||
        snapshot[15] !== 0 || ![PRODUCER_IDLE, PRODUCER_STARTED, PRODUCER_STOPPED]
            .includes(snapshot[6]) ||
        ![HOST_STATE_REGISTERED, HOST_STATE_STARTED, HOST_STATE_DRAINED,
          HOST_STATE_STOPPED, HOST_STATE_ERROR].includes(snapshot[13]) ||
        ![0, 1].includes(snapshot[12])) {
      this.setFailure("worklet-drain-invalid");
      return null;
    }
    // Both index pairs are uint32 monotonic counters. Compare only their
    // modular distances so a long-running stream can cross 2^32 safely.
    const occupancy = (snapshot[7] - snapshot[8]) >>> 0;
    const outstandingFrames = (snapshot[9] - snapshot[10]) >>> 0;
    if (occupancy > CAPACITY_FRAMES || outstandingFrames > CAPACITY_FRAMES) {
      this.setFailure("worklet-drain-invalid");
      return null;
    }
    return snapshot;
  }

  hasDrainedHeader() {
    const header = this.currentHeader();
    return header !== null && header[8] === header[7] &&
        header[7] === header[9] && header[9] >= TOTAL_FRAMES &&
        header[9] === TOTAL_FRAMES && header[10] === TOTAL_FRAMES &&
        header[12] === PRODUCER_ERROR_NONE &&
        header[13] === HOST_STATE_DRAINED;
  }

  hasStoppedHeader() {
    const header = this.currentHeader();
    return header !== null && header[6] === PRODUCER_STOPPED &&
        header[12] === PRODUCER_ERROR_NONE && this.hasDrainedHeader();
  }

  maybeCompleteNativeLifecycle() {
    if (this.failureCode !== null || this.nativeLifecycleComplete ||
        this.quiescenceScheduled || this.markerIndex !== EXPECTED_MARKERS.length ||
        !this.runtimeInitialized || !this.factorySettled ||
        !this.normalModuleExitObserved || this.onExitCount !== 1 ||
        this.runtimeExitCode !== 0 || !this.unregisterObserved ||
        !this.workletDrained || !this.startObserved || !this.stopObserved ||
        !this.hasStoppedHeader()) {
      return;
    }
    this.quiescenceScheduled = true;
    this.callbacksAtQuiescenceStart = this.callbackCount;
    setTimeout(() => {
      if (this.failureCode !== null ||
          this.callbacksAtQuiescenceStart !== this.callbackCount ||
          !this.hasStoppedHeader()) {
        this.setFailure("worklet-drain-invalid");
        return;
      }
      this.nativeLifecycleComplete = true;
      if (!this.finished) {
        this.finished = true;
        this.completion.resolve(true);
      }
    }, FINAL_QUIESCENCE_MS);
  }

  async loadRuntime() {
    if (!documentPrerequisites()) {
      fail("document-prerequisite");
    }
    setDocumentState("awaiting-native");
    this.wasmMemory = createWasmMemory();
    this.startMemoryWatchdog();
    if (!this.verifyMemoryIdentity()) {
      fail("memory-identity-invalid");
    }
    if (globalThis[HOST_BRIDGE_NAME] !== undefined) {
      fail("bridge-install-failed");
    }
    globalThis[HOST_BRIDGE_NAME] = this.bridge;
    let loader;
    try {
      const moduleUrl = new URL("./artifacts/" + this.context.moduleName + ".js",
                                location.href);
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
      const mainScriptUrlOrBlob = await awaitBeforeDeadline(response.blob(),
          this.deadline, "module-loader-failed");
      if (mainScriptUrlOrBlob.size === 0) {
        fail("module-loader-failed");
      }
      const namespace = await awaitBeforeDeadline(import(moduleUrl.href), this.deadline,
                                                   "module-loader-failed");
      if (typeof namespace.default !== "function") {
        fail("module-loader-failed");
      }
      loader = {mainScriptUrlOrBlob, moduleUrl, namespace};
    } catch (error) {
      fail(fixedFailureCode(error) === "host-exception" ?
          "module-loader-failed" : fixedFailureCode(error));
    }
    try {
      const factory = loader.namespace.default({
        mainScriptUrlOrBlob: loader.mainScriptUrlOrBlob,
        noExitRuntime: false,
        wasmMemory: this.wasmMemory,
        locateFile: (path) => {
          if (typeof path !== "string" || path !== `${this.context.moduleName}.wasm`) {
            fail("module-loader-failed");
          }
          return new URL(path, loader.moduleUrl).href;
        },
        print: (line) => this.captureNativeOutput("stdout", line),
        printErr: (line) => this.captureNativeOutput("stderr", line),
        onAbort: () => this.onAbort(),
        onExit: (code) => this.onExit(code),
        onRuntimeInitialized: () => this.onRuntimeInitialized(),
      });
      Promise.resolve(factory).then(
          (module) => this.onFactorySettled(module),
          (error) => this.onFactoryRejected(error));
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

  stopWorkletNow() {
    if (this.workletNode === null) {
      return;
    }
    this.workletStopRequested = true;
    try {
      this.workletNode.port.postMessage({protocol: DESCRIPTOR_PROTOCOL, type: "stop"});
    } catch (_error) {
      // A fixed cleanup failure is reflected only if pass would otherwise hold.
    }
    try {
      this.workletNode.disconnect();
      this.workletDisconnected = true;
    } catch (_error) {
      if (this.failureCode === null) {
        this.setFailure("cleanup-invalid");
      }
    }
  }

  async cleanup() {
    this.startButton.disabled = true;
    this.stopWorkletNow();
    if (this.descriptor !== null && this.failureCode === null) {
      const header = this.currentHeader();
      if (header !== null && header[13] !== HOST_STATE_ERROR) {
        Atomics.store(this.descriptor.header, 13, HOST_STATE_STOPPED);
      }
    }
    if (this.descriptor !== null) {
      this.finalHeader = headerSnapshot(this.descriptor.header);
    }
    if (this.audioContext !== null) {
      try {
        await awaitBeforeDeadline(this.audioContext.close(),
          performance.now() + CLEANUP_TIMEOUT_MS, "audio-context-close-failed");
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
    this.stopMemoryWatchdog();
    this.descriptor = null;
    this.wasmMemory = null;
    if (globalThis[HOST_BRIDGE_NAME] === this.bridge) {
      delete globalThis[HOST_BRIDGE_NAME];
    }
    this.cleanupComplete = true;
  }

  makeFailureResult() {
    const failureClass = this.nativeFailureStage !== null ?
        "native-fixed-failure" : this.failureCode === "runtime-startup-timeout" ||
            this.failureCode === "worklet-drain-timeout" ? "host-timeout" :
            this.failureCode === "host-exception" ? "host-exception" :
            "host-lifecycle";
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status: "fail",
      failureClass,
      firstFatalTag: this.firstFatalTag,
      nativeFailureStage: this.nativeFailureStage,
      lifecycle: {
        cleanupComplete: this.cleanupComplete,
        descriptorRegistered: this.descriptorRegistered,
        factorySettled: this.factorySettled,
        markerCount: this.nativeMarkers.length,
        normalExitObserved: this.normalModuleExitObserved,
        outputArmed: this.outputArmed,
        runtimeInitialized: this.runtimeInitialized,
        unregisterObserved: this.unregisterObserved,
        workletDrained: this.workletDrained,
        workletReady: this.workletReady,
      },
    };
  }

  makeSuccessResult() {
    const header = this.finalHeader;
    const pass = this.failureCode === null && this.nativeLifecycleComplete &&
        this.cleanupComplete && this.audioContextClosed && this.workletDisconnected &&
        this.workletStopRequested && this.descriptorRegistered &&
        this.descriptorRegistrationCount === 1 && this.unregisterObserved &&
        this.nativeMarkers.length === EXPECTED_MARKERS.length &&
        exactJsonEqual(this.nativeMarkers, EXPECTED_MARKERS) &&
        this.nativeMarkerSequenceAccepted && this.runtimeInitialized &&
        this.factorySettled && !this.runtimeAborted && this.onExitCount === 1 &&
        this.runtimeExitCode === 0 && this.normalModuleExitObserved &&
        this.trustedGesture && this.resumeRequestedInTrustedGesture &&
        this.audioContextRunning && this.workletReady && this.workletProgressObserved &&
        this.workletDrained && this.outputArmed && this.startObserved &&
        this.stopObserved && this.fixedGainPathProven && this.memoryIdentityStable &&
        this.memoryIdentityChecks > 0 &&
        Array.isArray(header) && header.length === HEADER_WORDS &&
        header[6] === PRODUCER_STOPPED && header[7] === TOTAL_FRAMES &&
        header[8] === TOTAL_FRAMES && header[9] === TOTAL_FRAMES &&
        header[10] === TOTAL_FRAMES && header[12] === PRODUCER_ERROR_NONE &&
        header[13] === HOST_STATE_STOPPED && header[14] === 0 && header[15] === 0 &&
        this.workletFramesRead === TOTAL_FRAMES &&
        this.workletNonSilentFrames === TOTAL_FRAMES &&
        isBoundedCount(this.workletUnderrunFrames, MAX_UNDERRUN_FRAMES);
    if (!pass || header === null || this.context.artifact.moduleName !== this.context.moduleName) {
      return this.makeFailureResult();
    }
    return {
      protocol: HOST_PROTOCOL,
      case: CASE,
      scope: SCOPE,
      status: "pass",
      failureCode: null,
      fixedGainPathProven: true,
      limitations: [...LIMITATIONS],
      artifact: this.context.artifact,
      captureHarness: this.context.captureHarness,
      versions: this.context.versions,
      origin: location.origin,
      secureContext: globalThis.isSecureContext === true,
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      sharedArrayBuffer: typeof SharedArrayBuffer === "function",
      sameOriginDocument: true,
      descriptorProtocol: DESCRIPTOR_PROTOCOL,
      capacityFrames: CAPACITY_FRAMES,
      channels: CHANNELS,
      sampleRate: SAMPLE_RATE,
      framesPerBuffer: FRAMES_PER_BUFFER,
      totalFrames: TOTAL_FRAMES,
      descriptorRegistered: true,
      descriptorRegistrationCount: 1,
      descriptorGeneration: header[5],
      descriptorValidated: true,
      memoryIdentityStable: true,
      memoryIdentityChecks: this.memoryIdentityChecks,
      nativeMarkerSource: "stderr-only",
      nativeMarkers: [...this.nativeMarkers],
      nativeMarkerSequenceAccepted: true,
      runtimeInitialized: true,
      runtimeFactorySettled: true,
      runtimeAborted: false,
      onExitCount: 1,
      runtimeExitCode: 0,
      normalModuleExitObserved: true,
      trustedGesture: true,
      resumeRequestedInTrustedGesture: true,
      audioContextRunning: true,
      workletReady: true,
      workletProgressObserved: true,
      workletDrained: true,
      outputArmed: true,
      startObserved: true,
      stopObserved: true,
      unregisterObserved: true,
      producedFrames: header[9],
      consumedFrames: header[10],
      workletFramesRead: this.workletFramesRead,
      workletNonSilentFrames: this.workletNonSilentFrames,
      underrunFrames: this.workletUnderrunFrames,
      producerError: header[12],
      hostState: header[13],
      workletStopRequested: true,
      workletDisconnected: true,
      audioContextClosed: true,
      cleanupComplete: true,
      m8GateComplete: false,
      audioManagerOutputPathProven: true,
      audioServiceIntegrated: false,
      inputProven: false,
      deviceChangePolicyProven: false,
      mutePolicyProven: false,
      tabSwitchingProven: false,
      browserMediaPlaybackProven: false,
      normalRuntimeShutdownProven: false,
    };
  }

  async run() {
    try {
      await awaitBeforeDeadline(this.loadRuntime(), this.deadline,
                                "runtime-startup-timeout");
      const readyOrCompletion = await awaitBeforeDeadline(Promise.race([
        this.readySignal.promise.then(() => "ready"),
        this.completion.promise.then(() => "completion"),
      ]), this.deadline, "runtime-startup-timeout");
      if (readyOrCompletion === "ready" && this.failureCode === null) {
        await this.postReady();
        const completed = await awaitBeforeDeadline(this.completion.promise,
            this.deadline, "worklet-drain-timeout");
        if (completed !== true && this.failureCode === null) {
          this.setFailure("host-exception");
        }
      }
    } catch (error) {
      this.setFailure(fixedFailureCode(error));
    }
    await this.cleanup();
    const result = this.makeSuccessResult();
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

function requireExactFields(value, keys) {
  if (!hasExactKeys(value, keys)) {
    throw new Error("invalid M8 audio output result schema");
  }
  return value;
}

export function validateM8AudioManagerOutputFailureSummary(value) {
  const result = requireExactFields(value, FAILURE_FIELDS);
  if (result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
      result.scope !== SCOPE || result.status !== "fail" ||
      !FAILURE_CLASSES.has(result.failureClass) ||
      !(result.firstFatalTag === null || FATAL_TAGS.has(result.firstFatalTag)) ||
      !(result.nativeFailureStage === null ||
        FAILURE_STAGES.has(result.nativeFailureStage)) ||
      !hasExactKeys(result.lifecycle, FAILURE_LIFECYCLE_FIELDS)) {
    throw new Error("invalid M8 audio output failure result");
  }
  for (const field of FAILURE_LIFECYCLE_FIELDS) {
    const entry = result.lifecycle[field];
    if (field === "markerCount") {
      if (!isBoundedCount(entry, EXPECTED_MARKERS.length)) {
        throw new Error("invalid M8 audio output failure lifecycle");
      }
    } else if (typeof entry !== "boolean") {
      throw new Error("invalid M8 audio output failure lifecycle");
    }
  }
  return result;
}

export function validateM8AudioManagerOutputResult(value) {
  const result = requireExactFields(value, SUCCESS_FIELDS);
  if (result.protocol !== HOST_PROTOCOL || result.case !== CASE ||
      result.scope !== SCOPE || result.status !== "pass" ||
      result.failureCode !== null || result.descriptorProtocol !== DESCRIPTOR_PROTOCOL ||
      result.capacityFrames !== CAPACITY_FRAMES || result.channels !== CHANNELS ||
      result.sampleRate !== SAMPLE_RATE || result.framesPerBuffer !== FRAMES_PER_BUFFER ||
      result.totalFrames !== TOTAL_FRAMES || result.nativeMarkerSource !== "stderr-only" ||
      !exactJsonEqual(result.nativeMarkers, EXPECTED_MARKERS) ||
      !exactJsonEqual(result.limitations, [...LIMITATIONS]) ||
      !asPositiveUint32(result.descriptorGeneration) ||
      !isBoundedCount(result.memoryIdentityChecks) ||
      result.memoryIdentityChecks === 0 ||
      !isBoundedCount(result.underrunFrames, MAX_UNDERRUN_FRAMES) ||
      result.producedFrames !== TOTAL_FRAMES || result.consumedFrames !== TOTAL_FRAMES ||
      result.workletFramesRead !== TOTAL_FRAMES ||
      result.workletNonSilentFrames !== TOTAL_FRAMES ||
      result.producerError !== PRODUCER_ERROR_NONE || result.hostState !== HOST_STATE_STOPPED ||
      !hasExactKeys(result.versions, ["chromium", "emscripten", "v8"]) ||
      !Object.values(result.versions).every((entry) =>
        typeof entry === "string" && REVISION_RE.test(entry))) {
    throw new Error("invalid M8 audio output success result");
  }
  for (const field of [
    "secureContext", "crossOriginIsolated", "sharedArrayBuffer",
    "sameOriginDocument", "descriptorRegistered", "descriptorValidated",
    "memoryIdentityStable", "nativeMarkerSequenceAccepted", "runtimeInitialized",
    "runtimeFactorySettled", "normalModuleExitObserved", "trustedGesture",
    "resumeRequestedInTrustedGesture", "audioContextRunning", "workletReady",
    "workletProgressObserved", "workletDrained", "outputArmed", "startObserved",
    "stopObserved", "unregisterObserved", "workletStopRequested",
    "workletDisconnected", "audioContextClosed", "cleanupComplete",
    "audioManagerOutputPathProven", "fixedGainPathProven",
  ]) {
    if (result[field] !== true) {
      throw new Error("invalid M8 audio output success flags");
    }
  }
  for (const field of [
    "runtimeAborted", "m8GateComplete", "audioServiceIntegrated", "inputProven",
    "deviceChangePolicyProven", "mutePolicyProven", "tabSwitchingProven",
    "browserMediaPlaybackProven", "normalRuntimeShutdownProven",
  ]) {
    if (result[field] !== false) {
      throw new Error("invalid M8 audio output nonclaim");
    }
  }
  if (result.descriptorRegistrationCount !== 1 || result.onExitCount !== 1 ||
      result.runtimeExitCode !== 0 || typeof result.origin !== "string" ||
      result.origin !== location.origin) {
    throw new Error("invalid M8 audio output lifecycle result");
  }
  validateArtifact(result.artifact, result.artifact.moduleName,
                   "document-prerequisite");
  validateCaptureHarness(result.captureHarness, "document-prerequisite");
  return result;
}

export async function runM8AudioManagerOutputSmokeFromQuery() {
  const context = parseM8AudioManagerOutputContext(location.search);
  const smoke = new M8AudioManagerOutputSmoke(context);
  return smoke.run();
}

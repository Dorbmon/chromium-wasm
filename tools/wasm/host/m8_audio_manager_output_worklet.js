// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// AudioWorklet consumer for the fixed v1 AudioManager output ring.  This file
// intentionally exposes only bounded counters and fixed protocol messages;
// samples and descriptor addresses never leave the worklet.

const PROTOCOL = 1;
const HEADER_WORDS = 16;
const HEADER_BYTES = HEADER_WORDS * Uint32Array.BYTES_PER_ELEMENT;
const CAPACITY_FRAMES = 4096;
const CHANNELS = 2;
const SAMPLE_RATE = 48000;
const FRAMES_PER_BUFFER = 480;
const TOTAL_FRAMES = 12000;
const PRODUCER_IDLE = 0;
const PRODUCER_STARTED = 1;
const PRODUCER_STOPPED = 2;
const PRODUCER_ERROR_NONE = 0;
const HOST_STATE_REGISTERED = 0;
const HOST_STATE_STARTED = 1;
const HOST_STATE_DRAINED = 2;
const HOST_STATE_STOPPED = 3;
const HOST_STATE_ERROR = 0xffffffff;
const PROGRESS_INTERVAL = 8;

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

function isUint32(value) {
  return Number.isSafeInteger(value) && value >= 0 && value <= 0xffffffff;
}

class ChromiumWasmM8AudioManagerOutputProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.failed = false;
    this.drained = false;
    this.stopRequested = false;
    this.processCalls = 0;
    this.framesRead = 0;
    this.nonSilentFrames = 0;
    this.header = null;
    this.samples = null;
    this.generation = 0;
    try {
      const descriptor = options?.processorOptions;
      if (!hasExactKeys(descriptor, [
        "generation", "headerByteOffset", "protocol", "ringBuffer",
        "samplesByteOffset",
      ]) || descriptor.protocol !== PROTOCOL ||
          !isUint32(descriptor.generation) || descriptor.generation === 0 ||
          !isUint32(descriptor.headerByteOffset) ||
          !isUint32(descriptor.samplesByteOffset) ||
          (descriptor.headerByteOffset & 3) !== 0 ||
          (descriptor.samplesByteOffset & 3) !== 0 ||
          !(descriptor.ringBuffer instanceof SharedArrayBuffer)) {
        this.fail("header-invalid");
        return;
      }
      const sampleBytes = CAPACITY_FRAMES * CHANNELS * Float32Array.BYTES_PER_ELEMENT;
      const headerEnd = descriptor.headerByteOffset + HEADER_BYTES;
      const samplesEnd = descriptor.samplesByteOffset + sampleBytes;
      if (!Number.isSafeInteger(headerEnd) || !Number.isSafeInteger(samplesEnd) ||
          headerEnd < descriptor.headerByteOffset ||
          samplesEnd < descriptor.samplesByteOffset ||
          headerEnd > descriptor.ringBuffer.byteLength ||
          samplesEnd > descriptor.ringBuffer.byteLength ||
          (headerEnd > descriptor.samplesByteOffset &&
           samplesEnd > descriptor.headerByteOffset)) {
        this.fail("header-invalid");
        return;
      }
      this.header = new Uint32Array(descriptor.ringBuffer,
                                    descriptor.headerByteOffset, HEADER_WORDS);
      this.samples = new Float32Array(descriptor.ringBuffer,
                                      descriptor.samplesByteOffset,
                                      CAPACITY_FRAMES * CHANNELS);
      this.generation = descriptor.generation;
      if (!this.validHeader()) {
        this.fail("header-invalid");
        return;
      }
      this.port.onmessage = (event) => this.onMessage(event.data);
      this.port.postMessage({protocol: PROTOCOL, type: "ready"});
    } catch (_error) {
      this.fail("processor-error");
    }
  }

  fail(code) {
    if (this.failed) {
      return;
    }
    this.failed = true;
    if (this.header instanceof Uint32Array) {
      try {
        Atomics.store(this.header, 13, HOST_STATE_ERROR);
      } catch (_error) {
        // The fixed error message remains sufficient.
      }
    }
    this.port.postMessage({code, protocol: PROTOCOL, type: "error"});
  }

  onMessage(message) {
    if (!hasExactKeys(message, ["protocol", "type"]) ||
        message.protocol !== PROTOCOL || message.type !== "stop") {
      this.fail("worklet-message-invalid");
      return;
    }
    this.stopRequested = true;
  }

  validHeader() {
    if (!(this.header instanceof Uint32Array) || this.header.length !== HEADER_WORDS) {
      return false;
    }
    const expected = [
      PROTOCOL, CAPACITY_FRAMES, CHANNELS, SAMPLE_RATE, FRAMES_PER_BUFFER,
      this.generation,
    ];
    if (expected.some((value, index) => Atomics.load(this.header, index) !== value) ||
        Atomics.load(this.header, 14) !== 0 || Atomics.load(this.header, 15) !== 0) {
      return false;
    }
    const producerState = Atomics.load(this.header, 6);
    const hostState = Atomics.load(this.header, 13);
    const producerError = Atomics.load(this.header, 12);
    if (![PRODUCER_IDLE, PRODUCER_STARTED, PRODUCER_STOPPED].includes(producerState) ||
        ![HOST_STATE_REGISTERED, HOST_STATE_STARTED, HOST_STATE_DRAINED,
          HOST_STATE_STOPPED, HOST_STATE_ERROR].includes(hostState) ||
        ![PRODUCER_ERROR_NONE, 1].includes(producerError)) {
      return false;
    }
    const writeIndex = Atomics.load(this.header, 7);
    const readIndex = Atomics.load(this.header, 8);
    const producedFrames = Atomics.load(this.header, 9);
    const consumedFrames = Atomics.load(this.header, 10);
    // Both pairs are monotonic uint32 counters. Their modular distance—not a
    // signed comparison—defines capacity across the uint32 wrap boundary.
    return ((writeIndex - readIndex) >>> 0) <= CAPACITY_FRAMES &&
        ((producedFrames - consumedFrames) >>> 0) <= CAPACITY_FRAMES;
  }

  postProgress(type) {
    const header = this.header;
    const message = {
      consumedFrames: Atomics.load(header, 10),
      framesRead: this.framesRead >>> 0,
      nonSilentFrames: this.nonSilentFrames >>> 0,
      processCalls: this.processCalls >>> 0,
      protocol: PROTOCOL,
      readIndex: Atomics.load(header, 8),
      type,
      underrunFrames: Atomics.load(header, 11),
      writeIndex: Atomics.load(header, 7),
    };
    if (type === "drained") {
      message.producedFrames = Atomics.load(header, 9);
    }
    this.port.postMessage(message);
  }

  zero(output, frames) {
    for (const channel of output) {
      channel.fill(0, 0, frames);
    }
  }

  process(_inputs, outputs) {
    if (this.failed || this.stopRequested) {
      return false;
    }
    try {
      const output = outputs[0];
      if (!Array.isArray(output) || output.length !== CHANNELS ||
          output.some((channel) => !(channel instanceof Float32Array)) ||
          output[0].length !== output[1].length || !this.validHeader()) {
        this.fail("output-invalid");
        return false;
      }
      const header = this.header;
      const hostState = Atomics.load(header, 13);
      const producerState = Atomics.load(header, 6);
      if (hostState === HOST_STATE_ERROR || Atomics.load(header, 12) !== 0) {
        this.fail("producer-error");
        return false;
      }
      if (producerState === PRODUCER_STARTED && hostState === HOST_STATE_REGISTERED) {
        this.fail("header-invalid");
        return false;
      }
      let writeIndex = Atomics.load(header, 7);
      let readIndex = Atomics.load(header, 8);
      let available = (writeIndex - readIndex) >>> 0;
      if (available > CAPACITY_FRAMES) {
        this.fail("header-invalid");
        return false;
      }
      const frames = output[0].length;
      let consumedThisCall = 0;
      for (let frame = 0; frame !== frames; ++frame) {
        if (available === 0) {
          output[0][frame] = 0;
          output[1][frame] = 0;
          if (hostState !== HOST_STATE_REGISTERED) {
            Atomics.add(header, 11, 1);
          }
          continue;
        }
        const slot = readIndex & (CAPACITY_FRAMES - 1);
        const left = this.samples[slot * CHANNELS];
        const right = this.samples[slot * CHANNELS + 1];
        if (!Number.isFinite(left) || !Number.isFinite(right)) {
          this.fail("processor-error");
          return false;
        }
        output[0][frame] = left;
        output[1][frame] = right;
        if (left !== 0 || right !== 0) {
          this.nonSilentFrames = (this.nonSilentFrames + 1) >>> 0;
        }
        readIndex = (readIndex + 1) >>> 0;
        available -= 1;
        consumedThisCall += 1;
      }
      if (consumedThisCall !== 0) {
        Atomics.store(header, 8, readIndex);
        Atomics.add(header, 10, consumedThisCall);
        this.framesRead = (this.framesRead + consumedThisCall) >>> 0;
      }
      this.processCalls = (this.processCalls + 1) >>> 0;
      writeIndex = Atomics.load(header, 7);
      const producedFrames = Atomics.load(header, 9);
      const consumedFrames = Atomics.load(header, 10);
      const finalReadIndex = Atomics.load(header, 8);
      if (!this.drained && finalReadIndex === writeIndex &&
          writeIndex === producedFrames && producedFrames >= TOTAL_FRAMES &&
          producedFrames === TOTAL_FRAMES && consumedFrames === TOTAL_FRAMES &&
          this.framesRead === TOTAL_FRAMES && this.nonSilentFrames === TOTAL_FRAMES) {
        Atomics.store(header, 13, HOST_STATE_DRAINED);
        this.drained = true;
        this.postProgress("drained");
      } else if (!this.drained && this.processCalls % PROGRESS_INTERVAL === 0) {
        this.postProgress("progress");
      }
      return true;
    } catch (_error) {
      this.fail("processor-error");
      return false;
    }
  }
}

registerProcessor("chromium-wasm-m8-audio-manager-output",
                  ChromiumWasmM8AudioManagerOutputProcessor);

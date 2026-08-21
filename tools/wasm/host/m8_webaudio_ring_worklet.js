// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Browser-owned AudioWorklet consumer for the target-local M8 PCM ring.
// This file has no Chromium dependency and intentionally knows only the
// one fixed SharedArrayBuffer descriptor passed in processorOptions.

const PROTOCOL = 1;
const HEADER_PROTOCOL = 0;
const HEADER_CAPACITY_FRAMES = 1;
const HEADER_CHANNELS = 2;
const HEADER_START_REQUESTED = 3;
const HEADER_PRODUCER_STARTED = 4;
const HEADER_PRODUCER_DONE = 5;
const HEADER_WRITE_FRAME = 6;
const HEADER_READ_FRAME = 7;
const HEADER_PRODUCED_FRAMES = 8;
const HEADER_CONSUMED_FRAMES = 9;
const HEADER_UNDERRUN_FRAMES = 10;
const HEADER_PRODUCER_ERROR = 11;
const HEADER_WORDS = 12;
const CAPACITY_FRAMES = 4096;
const CHANNELS = 2;
const TOTAL_FRAMES = 12288;
const ERROR_INVALID_DESCRIPTOR = "invalid-descriptor";
const ERROR_INVALID_OUTPUT = "invalid-output";
const ERROR_INVALID_RING = "invalid-ring";
const ERROR_INVALID_SAMPLE = "invalid-sample";
const ERROR_PROCESSOR_EXCEPTION = "processor-exception";
const STOP_MESSAGE = "stop";

function requireInteger(value, name, minimum, maximum) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(name + " is invalid");
  }
  return value;
}

function hasExactKeys(value, keys) {
  if (value === null || typeof value !== "object" ||
      Object.getPrototypeOf(value) !== Object.prototype) {
    return false;
  }
  const actualKeys = Object.keys(value).sort();
  const expectedKeys = [...keys].sort();
  return actualKeys.length === expectedKeys.length &&
      actualKeys.every((key, index) => key === expectedKeys[index]);
}

class ChromiumWasmM8WebAudioRingProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    try {
      const descriptor = options?.processorOptions;
      if (!hasExactKeys(descriptor, [
        "capacityFrames",
        "channels",
        "headerByteOffset",
        "protocol",
        "ringBuffer",
        "samplesByteOffset",
        "totalFrames",
      ]) || descriptor.protocol !== PROTOCOL ||
          !(descriptor.ringBuffer instanceof SharedArrayBuffer)) {
        throw new Error(ERROR_INVALID_DESCRIPTOR);
      }
      this.headerByteOffset = requireInteger(
          descriptor.headerByteOffset, "header byte offset", 0,
          descriptor.ringBuffer.byteLength -
              HEADER_WORDS * Int32Array.BYTES_PER_ELEMENT);
      this.samplesByteOffset = requireInteger(
          descriptor.samplesByteOffset, "samples byte offset", 0,
          descriptor.ringBuffer.byteLength);
      this.capacityFrames = requireInteger(
          descriptor.capacityFrames, "capacity frames", CAPACITY_FRAMES,
          CAPACITY_FRAMES);
      this.channels = requireInteger(
          descriptor.channels, "channels", CHANNELS, CHANNELS);
      this.totalFrames = requireInteger(
          descriptor.totalFrames, "total frames", TOTAL_FRAMES,
          TOTAL_FRAMES);
      const headerEnd = this.headerByteOffset +
          HEADER_WORDS * Int32Array.BYTES_PER_ELEMENT;
      const samplesEnd = this.samplesByteOffset +
          this.capacityFrames * this.channels * Float32Array.BYTES_PER_ELEMENT;
      if ((this.capacityFrames & (this.capacityFrames - 1)) !== 0 ||
          this.channels !== CHANNELS ||
          (this.headerByteOffset & 3) !== 0 ||
          (this.samplesByteOffset & 3) !== 0 ||
          headerEnd > descriptor.ringBuffer.byteLength ||
          samplesEnd > descriptor.ringBuffer.byteLength ||
          (headerEnd > this.samplesByteOffset &&
           samplesEnd > this.headerByteOffset)) {
        throw new Error(ERROR_INVALID_DESCRIPTOR);
      }
      this.ringBuffer = descriptor.ringBuffer;
      this.ringBufferByteLength = descriptor.ringBuffer.byteLength;
      this.header = new Int32Array(
          descriptor.ringBuffer, this.headerByteOffset, HEADER_WORDS);
      this.samples = new Float32Array(
          descriptor.ringBuffer, this.samplesByteOffset,
          this.capacityFrames * this.channels);
      if (Atomics.load(this.header, HEADER_PROTOCOL) !== PROTOCOL ||
          Atomics.load(this.header, HEADER_CAPACITY_FRAMES) !== this.capacityFrames ||
          Atomics.load(this.header, HEADER_CHANNELS) !== this.channels) {
        throw new Error(ERROR_INVALID_DESCRIPTOR);
      }
      this.processCalls = 0;
      this.framesRead = 0;
      this.nonSilentFrames = 0;
      this.underrunFrames = 0;
      this.drained = false;
      this.failed = false;
      this.stopRequested = false;
      this.port.onmessage = (event) => {
        const message = event.data;
        if (hasExactKeys(message, ["protocol", "type"]) &&
            message.protocol === PROTOCOL && message.type === STOP_MESSAGE) {
          this.stopRequested = true;
        }
      };
      this.port.postMessage({type: "ready", protocol: PROTOCOL});
    } catch (_error) {
      this.failed = true;
      this.port.postMessage({
        type: "error",
        protocol: PROTOCOL,
        code: ERROR_INVALID_DESCRIPTOR,
      });
    }
  }

  fail(code) {
    if (!this.failed) {
      this.failed = true;
      this.port.postMessage({
        type: "error",
        protocol: PROTOCOL,
        code,
      });
    }
    return false;
  }

  process(_inputs, outputs) {
    if (this.failed || this.stopRequested) {
      return false;
    }
    try {
      // A growable shared buffer can retain its identity while changing its
      // visible size. The page watchdog detects identity swaps; reject a
      // length change locally before consuming an obsolete ring layout.
      if (this.ringBuffer.byteLength !== this.ringBufferByteLength ||
          this.header.buffer !== this.ringBuffer ||
          this.samples.buffer !== this.ringBuffer) {
        return this.fail(ERROR_INVALID_RING);
      }
      const output = outputs[0];
      if (!Array.isArray(output) || output.length !== this.channels ||
          !(output[0] instanceof Float32Array) ||
          !(output[1] instanceof Float32Array) ||
          output[0].length !== output[1].length) {
        return this.fail(ERROR_INVALID_OUTPUT);
      }
      const frameCount = output[0].length;
      let read = Atomics.load(this.header, HEADER_READ_FRAME);
      const write = Atomics.load(this.header, HEADER_WRITE_FRAME);
      let available = write - read;
      if (!Number.isSafeInteger(read) || !Number.isSafeInteger(write) ||
          available < 0 || available > this.capacityFrames ||
          Atomics.load(this.header, HEADER_PRODUCER_ERROR) !== 0) {
        return this.fail(ERROR_INVALID_RING);
      }

      for (let frame = 0; frame < frameCount; ++frame) {
        if (available > 0) {
          const slot = read & (this.capacityFrames - 1);
          const left = this.samples[slot * this.channels];
          const right = this.samples[slot * this.channels + 1];
          if (!Number.isFinite(left) || !Number.isFinite(right)) {
            return this.fail(ERROR_INVALID_SAMPLE);
          }
          output[0][frame] = left;
          output[1][frame] = right;
          if (Math.abs(left) > 0.01 || Math.abs(right) > 0.01) {
            ++this.nonSilentFrames;
          }
          ++read;
          --available;
          ++this.framesRead;
        } else {
          output[0][frame] = 0;
          output[1][frame] = 0;
          ++this.underrunFrames;
        }
      }
      Atomics.store(this.header, HEADER_READ_FRAME, read);
      Atomics.store(this.header, HEADER_CONSUMED_FRAMES, this.framesRead);
      Atomics.store(this.header, HEADER_UNDERRUN_FRAMES, this.underrunFrames);
      ++this.processCalls;

      if (!this.drained && Atomics.load(this.header, HEADER_PRODUCER_DONE) === 1 &&
          read === Atomics.load(this.header, HEADER_WRITE_FRAME)) {
        this.drained = true;
        this.port.postMessage({
          type: "drained",
          protocol: PROTOCOL,
          processCalls: this.processCalls,
          framesRead: this.framesRead,
          nonSilentFrames: this.nonSilentFrames,
          underrunFrames: this.underrunFrames,
          producerStarted: Atomics.load(this.header, HEADER_PRODUCER_STARTED) === 1,
          producerDone: true,
        });
        return false;
      } else if (this.processCalls % 16 === 0) {
        this.port.postMessage({
          type: "progress",
          protocol: PROTOCOL,
          processCalls: this.processCalls,
          framesRead: this.framesRead,
          nonSilentFrames: this.nonSilentFrames,
          underrunFrames: this.underrunFrames,
          startRequested:
              Atomics.load(this.header, HEADER_START_REQUESTED) === 1,
        });
      }
      return true;
    } catch (_error) {
      return this.fail(ERROR_PROCESSOR_EXCEPTION);
    }
  }
}

registerProcessor(
    "chromium-wasm-m8-webaudio-ring",
    ChromiumWasmM8WebAudioRingProcessor);

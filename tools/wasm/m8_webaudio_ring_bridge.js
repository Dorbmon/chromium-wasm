// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Target-local C++/WebAudio bridge.  It accepts only the one fixed descriptor
// used by the feasibility target and deliberately never selects Chromium's
// AudioManager or AudioService.  The host, not this bridge, owns WebAudio.

mergeInto(LibraryManager.library, {
  $M8WebAudioRingBridge: {
    protocol: 1,
    headerWords: 12,
    capacityFrames: 4096,
    channels: 2,
    totalFrames: 12288,
    bridge() {
      const bridge = globalThis.__chromiumWasmM8WebAudioRingHostV1;
      return bridge !== null && typeof bridge === 'object' &&
          bridge.protocol === this.protocol ? bridge : null;
    },
    hasStableMemoryIdentity(bridge) {
      return bridge !== null &&
          typeof bridge.verifyMemoryIdentity === 'function' &&
          bridge.verifyMemoryIdentity() === true;
    },
    unsignedPointer(value) {
      if (!Number.isInteger(value)) {
        return null;
      }
      return value >>> 0;
    },
    validDescriptor(headerAddress, samplesAddress, capacityFrames, channels,
                    totalFrames) {
      const header = this.unsignedPointer(headerAddress);
      const samples = this.unsignedPointer(samplesAddress);
      if (header === null || samples === null ||
          capacityFrames !== this.capacityFrames ||
          channels !== this.channels || totalFrames !== this.totalFrames ||
          (header & 3) !== 0 || (samples & 3) !== 0) {
        return null;
      }
      const headerBytes = this.headerWords * Int32Array.BYTES_PER_ELEMENT;
      const sampleBytes = capacityFrames * channels * Float32Array.BYTES_PER_ELEMENT;
      const headerEnd = header + headerBytes;
      const samplesEnd = samples + sampleBytes;
      if (!Number.isSafeInteger(headerEnd) || !Number.isSafeInteger(samplesEnd) ||
          headerEnd < header || samplesEnd < samples ||
          typeof HEAPU8 !== "object" || HEAPU8 === null ||
          !(HEAPU8.buffer instanceof SharedArrayBuffer) ||
          headerEnd > HEAPU8.byteLength || samplesEnd > HEAPU8.byteLength ||
          (headerEnd > samples && samplesEnd > header)) {
        return null;
      }
      const headerWords = new Int32Array(HEAPU8.buffer, header,
                                         this.headerWords);
      if (Atomics.load(headerWords, 0) !== this.protocol ||
          Atomics.load(headerWords, 1) !== this.capacityFrames ||
          Atomics.load(headerWords, 2) !== this.channels ||
          Atomics.load(headerWords, 3) !== 0 ||
          Atomics.load(headerWords, 4) !== 0 ||
          Atomics.load(headerWords, 5) !== 0 ||
          Atomics.load(headerWords, 6) !== 0 ||
          Atomics.load(headerWords, 7) !== 0 ||
          Atomics.load(headerWords, 8) !== 0 ||
          Atomics.load(headerWords, 9) !== 0 ||
          Atomics.load(headerWords, 10) !== 0 ||
          Atomics.load(headerWords, 11) !== 0) {
        return null;
      }
      return {
        protocol: this.protocol,
        ringBuffer: HEAPU8.buffer,
        headerByteOffset: header,
        samplesByteOffset: samples,
        capacityFrames: this.capacityFrames,
        channels: this.channels,
        totalFrames: this.totalFrames,
      };
    },
  },

  m8_webaudio_ring_register__deps: ['$M8WebAudioRingBridge'],
  // main() runs on Emscripten's application pthread.  Registering the
  // descriptor must happen on the browser main thread, but the bridge never
  // starts an AudioContext; the host waits for its trusted Start click.
  m8_webaudio_ring_register__proxy: 'sync',
  m8_webaudio_ring_register: (
      headerAddress, samplesAddress, capacityFrames, channels, totalFrames) => {
    try {
      const bridge = M8WebAudioRingBridge.bridge();
      const descriptor = M8WebAudioRingBridge.validDescriptor(
          headerAddress, samplesAddress, capacityFrames, channels, totalFrames);
      if (bridge === null || descriptor === null ||
          typeof bridge.registerRing !== 'function') {
        return 0;
      }
      return bridge.registerRing(descriptor) === true ? 1 : 0;
    } catch (_error) {
      return 0;
    }
  },

  m8_webaudio_ring_report_producer_started__deps: ['$M8WebAudioRingBridge'],
  m8_webaudio_ring_report_producer_started__proxy: 'sync',
  m8_webaudio_ring_report_producer_started: () => {
    try {
      const bridge = M8WebAudioRingBridge.bridge();
      return M8WebAudioRingBridge.hasStableMemoryIdentity(bridge) &&
          typeof bridge.reportProducerStarted === 'function' &&
          bridge.reportProducerStarted() === true ? 1 : 0;
    } catch (_error) {
      return 0;
    }
  },

  m8_webaudio_ring_report_producer_finished__deps: ['$M8WebAudioRingBridge'],
  m8_webaudio_ring_report_producer_finished__proxy: 'sync',
  m8_webaudio_ring_report_producer_finished: (totalFrames) => {
    try {
      const bridge = M8WebAudioRingBridge.bridge();
      if (!M8WebAudioRingBridge.hasStableMemoryIdentity(bridge) ||
          typeof bridge.reportProducerFinished !== 'function' ||
          !Number.isSafeInteger(totalFrames) || totalFrames <= 0) {
        return 0;
      }
      return bridge.reportProducerFinished(totalFrames) === true ? 1 : 0;
    } catch (_error) {
      return 0;
    }
  },
});

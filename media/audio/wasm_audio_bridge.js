// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// The control-plane half of the Wasm AudioOutputStream bridge.  This library
// is linked into Wasm media closures, but it exposes no device unless the
// outer page has installed the exact versioned host object after a trusted
// user gesture.  The steady-state PCM path is the validated SharedArrayBuffer
// descriptor; no audio quantum crosses this JS/C++ boundary.

mergeInto(LibraryManager.library, {
  $ChromiumWasmAudioBridge: {
    protocol: 1,
    headerWords: 16,
    capacityFrames: 4096,
    channels: 2,
    sampleRate: 48000,
    framesPerBuffer: 480,

    bridge() {
      const bridge = globalThis.__chromiumWasmAudioHostV1;
      if (bridge === null || typeof bridge !== "object" ||
          bridge.protocol !== this.protocol ||
          typeof bridge.isOutputArmed !== "function" ||
          typeof bridge.registerOutputRing !== "function" ||
          typeof bridge.unregisterOutputRing !== "function") {
        return null;
      }
      return bridge;
    },

    unsignedPointer(value) {
      return Number.isInteger(value) ? value >>> 0 : null;
    },

    descriptor(headerAddress, samplesAddress, capacityFrames, channels,
               sampleRate, framesPerBuffer, generation) {
      const header = this.unsignedPointer(headerAddress);
      const samples = this.unsignedPointer(samplesAddress);
      const normalizedGeneration = this.unsignedPointer(generation);
      if (header === null || samples === null ||
          capacityFrames !== this.capacityFrames || channels !== this.channels ||
          sampleRate !== this.sampleRate ||
          framesPerBuffer !== this.framesPerBuffer ||
          normalizedGeneration === null || normalizedGeneration === 0 ||
          (header & 3) !== 0 || (samples & 3) !== 0 ||
          typeof HEAPU8 !== "object" || HEAPU8 === null ||
          !(HEAPU8.buffer instanceof SharedArrayBuffer)) {
        return null;
      }

      const headerBytes = this.headerWords * Uint32Array.BYTES_PER_ELEMENT;
      const sampleBytes = capacityFrames * channels * Float32Array.BYTES_PER_ELEMENT;
      const headerEnd = header + headerBytes;
      const samplesEnd = samples + sampleBytes;
      if (!Number.isSafeInteger(headerEnd) || !Number.isSafeInteger(samplesEnd) ||
          headerEnd < header || samplesEnd < samples ||
          headerEnd > HEAPU8.byteLength || samplesEnd > HEAPU8.byteLength ||
          (headerEnd > samples && samplesEnd > header)) {
        return null;
      }

      const words = new Uint32Array(HEAPU8.buffer, header, this.headerWords);
      if (Atomics.load(words, 0) !== this.protocol ||
          Atomics.load(words, 1) !== this.capacityFrames ||
          Atomics.load(words, 2) !== this.channels ||
          Atomics.load(words, 3) !== this.sampleRate ||
          Atomics.load(words, 4) !== this.framesPerBuffer ||
          Atomics.load(words, 5) !== normalizedGeneration ||
          Atomics.load(words, 6) !== 0 || Atomics.load(words, 7) !== 0 ||
          Atomics.load(words, 8) !== 0 || Atomics.load(words, 9) !== 0 ||
          Atomics.load(words, 10) !== 0 || Atomics.load(words, 11) !== 0 ||
          Atomics.load(words, 12) !== 0 || Atomics.load(words, 13) !== 0 ||
          Atomics.load(words, 14) !== 0 || Atomics.load(words, 15) !== 0) {
        return null;
      }

      return Object.freeze({
        protocol: this.protocol,
        generation: normalizedGeneration,
        ringBuffer: HEAPU8.buffer,
        headerByteOffset: header,
        samplesByteOffset: samples,
        capacityFrames: this.capacityFrames,
        channels: this.channels,
        sampleRate: this.sampleRate,
        framesPerBuffer: this.framesPerBuffer,
      });
    },
  },

  chromium_wasm_audio_output_is_armed__deps: ['$ChromiumWasmAudioBridge'],
  chromium_wasm_audio_output_is_armed__proxy: 'sync',
  chromium_wasm_audio_output_is_armed: () => {
    try {
      const bridge = ChromiumWasmAudioBridge.bridge();
      return bridge !== null && bridge.isOutputArmed() === true ? 1 : 0;
    } catch (_error) {
      return 0;
    }
  },

  chromium_wasm_audio_output_register__deps: ['$ChromiumWasmAudioBridge'],
  chromium_wasm_audio_output_register__proxy: 'sync',
  chromium_wasm_audio_output_register: (
      headerAddress, samplesAddress, capacityFrames, channels, sampleRate,
      framesPerBuffer, generation) => {
    try {
      const bridge = ChromiumWasmAudioBridge.bridge();
      const descriptor = ChromiumWasmAudioBridge.descriptor(
          headerAddress, samplesAddress, capacityFrames, channels, sampleRate,
          framesPerBuffer, generation);
      // Descriptor registration intentionally precedes the trusted gesture:
      // the host needs the exact native ring before it can create a worklet.
      // Start() independently queries isOutputArmed() after that gesture.
      if (bridge === null || descriptor === null) {
        return 0;
      }
      return bridge.registerOutputRing(descriptor) === true ? 1 : 0;
    } catch (_error) {
      return 0;
    }
  },

  chromium_wasm_audio_output_unregister__deps: ['$ChromiumWasmAudioBridge'],
  chromium_wasm_audio_output_unregister__proxy: 'sync',
  chromium_wasm_audio_output_unregister: (generation) => {
    try {
      const bridge = ChromiumWasmAudioBridge.bridge();
      const normalizedGeneration =
          ChromiumWasmAudioBridge.unsignedPointer(generation);
      if (bridge === null || normalizedGeneration === null ||
          normalizedGeneration === 0) {
        return;
      }
      bridge.unregisterOutputRing(normalizedGeneration);
    } catch (_error) {
      // Close() must remain idempotent even if the host has already discarded
      // an aborted worklet.  The C++ stream still drops its retained state.
    }
  },
});

// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This library is linked only by the dedicated M7 failure-diagnostic target.
// It deliberately replaces the implementation but not the existing Emscripten
// ABI declaration for _abort_js.
addToLibrary({
  _abort_js: () => {
    let marker = 'CHROMIUM_WASM_M7_ABORT_PC:unavailable';
    try {
      const stack = new Error().stack;
      if (typeof stack === 'string') {
        const wasmFrame =
            /^wasm-function\[(0|[1-9][0-9]{0,9})\]:0x([0-9a-fA-F]{1,8})(?![0-9a-fA-F])/;
        const wasmFramePrefix = 'wasm-function[';
        const nextWasmFrame = (startIndex) => {
          const frameStart = stack.indexOf(wasmFramePrefix, startIndex);
          if (frameStart === -1) {
            return null;
          }

          const frame = wasmFrame.exec(stack.slice(frameStart));
          if (!frame) {
            return null;
          }

          const functionIndex = Number(frame[1]);
          if (functionIndex > 0xffffffff) {
            return null;
          }

          return {
            functionIndex,
            offset: frame[2],
            nextIndex: frameStart + frame[0].length,
          };
        };
        const firstFrame = nextWasmFrame(0);
        const secondFrame =
            firstFrame && nextWasmFrame(firstFrame.nextIndex);
        const callerCallerFrame =
            secondFrame && nextWasmFrame(secondFrame.nextIndex);
        if (callerCallerFrame) {
          const offset = callerCallerFrame.offset.toLowerCase().replace(
              /^0+(?=[0-9a-f])/, '');
          marker = 'CHROMIUM_WASM_M7_ABORT_PC:frame=caller-caller;function=' +
              callerCallerFrame.functionIndex + ';offset=0x' + offset;
        }
      }
    } catch {
      // The diagnostic must not change abort behavior when Error.stack is
      // unavailable in a worker.
    }

    try {
      err(marker);
    } finally {
#if ASSERTIONS
      abort('native code called abort()');
#else
      abort('');
#endif
    }
  },
});

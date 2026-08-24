// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This is deliberately a polling bridge. Browser online/offline events run on
// the JavaScript main thread, while the NetworkChangeNotifier is owned by a
// Chromium sequence. Events only update this JavaScript-owned scalar; C++
// observes it through a synchronous proxied import and never receives a direct
// DOM callback.
//
// The state is advisory. `online` never means that Chromium can reach a
// destination, and this bridge does not expose interface, DNS, metering, or
// transport information.
mergeInto(LibraryManager.library, {
  $ChromiumWasmNetworkChangeNotifier: {
    // This version is part of the C++/JavaScript bridge ABI. Keep it in sync
    // with net/base/network_change_notifier_wasm.cc.
    version: 1,

    states: Object.freeze({
      unknown: 0,
      offline: 1,
      online: 2,
    }),

    state: 0,
    started: false,

    snapshotState() {
      try {
        if (typeof navigator !== 'object' || navigator === null ||
            typeof navigator.onLine !== 'boolean') {
          return this.states.unknown;
        }
        return navigator.onLine ? this.states.online : this.states.offline;
      } catch (_) {
        return this.states.unknown;
      }
    },

    ensureStarted() {
      if (this.started) {
        return;
      }
      this.started = true;
      this.state = this.snapshotState();
      try {
        if (typeof globalThis.addEventListener !== 'function') {
          return;
        }
        globalThis.addEventListener('online', () => {
          this.state = this.states.online;
        });
        globalThis.addEventListener('offline', () => {
          this.state = this.states.offline;
        });
      } catch (_) {
        // A host that cannot register the advisory events remains unknown.
        this.state = this.states.unknown;
      }
    },

    query(bridgeVersion) {
      if (bridgeVersion !== this.version) {
        return this.states.unknown;
      }
      this.ensureStarted();
      return this.state;
    },
  },

  chromium_wasm_network_change_notifier_state__deps: [
    '$ChromiumWasmNetworkChangeNotifier',
  ],
  chromium_wasm_network_change_notifier_state__proxy: 'sync',
  chromium_wasm_network_change_notifier_state: (bridgeVersion) => {
    return ChromiumWasmNetworkChangeNotifier.query(bridgeVersion);
  },
});

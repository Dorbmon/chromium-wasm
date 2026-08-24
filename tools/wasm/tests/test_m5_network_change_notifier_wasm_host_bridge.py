#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Behavior contracts for the passive Wasm network-state host bridge."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]
BRIDGE = ROOT_DIR / "net/base/network_change_notifier_wasm.js"
PINNED_NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"


def node_executable() -> str | None:
    path_node = shutil.which("node")
    if path_node:
        return path_node
    if PINNED_NODE.is_file():
        return str(PINNED_NODE)
    return None


class M5NetworkChangeNotifierWasmHostBridgeTest(unittest.TestCase):
    def test_bridge_is_versioned_sync_and_does_not_claim_transport_state(
        self,
    ) -> None:
        source = BRIDGE.read_text(encoding="utf-8")

        for marker in (
            "version: 1",
            "unknown: 0",
            "offline: 1",
            "online: 2",
            "globalThis.addEventListener('online'",
            "globalThis.addEventListener('offline'",
            "chromium_wasm_network_change_notifier_state__proxy: 'sync'",
            "ChromiumWasmNetworkChangeNotifier.query(bridgeVersion)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

        for forbidden in (
            "fetch(",
            "WebSocket",
            "XMLHttpRequest",
            "HEAP",
            "Module",
            "ccall",
            "Wisp",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_bridge_parses_as_javascript(self) -> None:
        node = node_executable()
        if node is None:
            self.skipTest("Node is unavailable")
        completed = subprocess.run(
            [node, "--check", str(BRIDGE)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_online_offline_events_only_update_the_polled_scalar(self) -> None:
        node = node_executable()
        if node is None:
            self.skipTest("Node is unavailable")

        script = r"""
const assert = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};
const fs = require('fs');
const vm = require('vm');

function load(navigatorValue) {
  const listeners = new Map();
  const library = {};
  const context = {
    Map,
    Object,
    navigator: navigatorValue,
    LibraryManager: {library},
  };
  context.globalThis = context;
  context.addEventListener = (name, callback) => {
    const callbacks = listeners.get(name) || [];
    callbacks.push(callback);
    listeners.set(name, callbacks);
  };
  context.mergeInto = (target, definitions) => {
    Object.assign(target, definitions);
    for (const [name, value] of Object.entries(definitions)) {
      if (name.startsWith('$')) {
        context[name.substring(1)] = value;
      }
    }
  };
  vm.createContext(context);
  vm.runInContext(
      fs.readFileSync(__BRIDGE_PATH__, 'utf8'), context,
      {filename: 'network_change_notifier_wasm.js'});
  return {context, library, listeners};
}

function dispatch(loaded, name) {
  const callbacks = loaded.listeners.get(name) || [];
  for (const callback of callbacks) {
    callback({type: name});
  }
}

const online = load({onLine: true});
const query = online.library.chromium_wasm_network_change_notifier_state;
assert(online.library.chromium_wasm_network_change_notifier_state__proxy === 'sync',
    'bridge must synchronously proxy polling to the JavaScript main thread');
assert(query(1) === 2, 'initial online state was not mapped to the online enum');
assert(online.listeners.get('online').length === 1 &&
    online.listeners.get('offline').length === 1,
    'bridge did not install exactly one passive listener for each DOM event');
dispatch(online, 'offline');
assert(query(1) === 1, 'offline event did not update the scalar state');
dispatch(online, 'online');
assert(query(1) === 2, 'online event did not update the scalar state');

const unavailable = load(undefined);
assert(unavailable.library.chromium_wasm_network_change_notifier_state(1) === 0,
    'missing navigator state did not remain unknown');

const wrongVersion = load({onLine: false});
assert(wrongVersion.library.chromium_wasm_network_change_notifier_state(2) === 0,
    'an incompatible bridge version did not remain unknown');
assert(wrongVersion.listeners.size === 0,
    'an incompatible bridge version registered host event listeners');

console.log('M5_NETWORK_CHANGE_NOTIFIER_WASM_HOST_BRIDGE:PASS');
""".replace("__BRIDGE_PATH__", json.dumps(str(BRIDGE)))

        completed = subprocess.run(
            [node, "--input-type=commonjs"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "M5_NETWORK_CHANGE_NOTIFIER_WASM_HOST_BRIDGE:PASS",
            completed.stdout,
        )

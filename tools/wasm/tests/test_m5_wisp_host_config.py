#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests the credential-free host-to-WISP endpoint configuration boundary."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]
HOST = ROOT_DIR / "tools/wasm/host/content_shell_host.js"
PINNED_NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"


def node_executable() -> str | None:
    path_node = shutil.which("node")
    if path_node:
        return path_node
    if PINNED_NODE.is_file():
        return str(PINNED_NODE)
    return None


class M5WispHostConfigTest(unittest.TestCase):
    def test_initialize_passes_only_normalized_wisp_config_to_module(self) -> None:
        source = HOST.read_text(encoding="utf-8")

        self.assertIn("export function normalizeWispConfiguration", source)
        self.assertIn("wisp = undefined", source)
        self.assertIn("moduleOptions.chromiumWasmWisp = wispConfiguration", source)
        self.assertIn("WISP configuration field is not allowed", source)
        self.assertIn("WISP endpoint violates the transport policy", source)
        self.assertIn("initialize:wisp-configured", source)
        self.assertNotIn("wispEndpoint", source)
        self.assertNotIn("wispToken", source)

    def test_endpoint_policy_and_option_bounds(self) -> None:
        node = node_executable()
        if node is None:
            self.skipTest("Node is unavailable")

        script = r"""
const assert = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};
const {normalizeWispConfiguration} = await import(__HOST_URL__);

function expectFailure(configuration, message) {
  let failed = false;
  try {
    normalizeWispConfiguration(configuration);
  } catch (_) {
    failed = true;
  }
  assert(failed, message);
}

assert(normalizeWispConfiguration(undefined) === undefined,
    'omitted endpoint must keep WISP disabled');
const configured = normalizeWispConfiguration({
  version: 1,
  endpoint: 'wss://wisp.example/proxy/',
  subprotocol: 'wisp-v2',
  maxDataFrameBytes: 4096,
  maxWebSocketBufferedBytes: 8192,
});
assert(Object.isFrozen(configured), 'normalized configuration must be frozen');
assert(configured.endpoint === 'wss://wisp.example/proxy/' &&
    configured.subprotocol === 'wisp-v2' &&
    configured.maxDataFrameBytes === 4096 &&
    configured.maxWebSocketBufferedBytes === 8192,
    'valid endpoint configuration was not copied exactly');
assert(!Object.hasOwn(configured, 'token'),
    'normalized configuration retained a credential field');

const loopback = normalizeWispConfiguration({
  version: 1,
  endpoint: 'ws://127.0.0.1:8787/',
});
assert(loopback.endpoint === 'ws://127.0.0.1:8787/',
    'deterministic loopback ws endpoint was rejected');

expectFailure(null, 'null configuration was accepted');
expectFailure({version: 1, endpoint: 'ws://wisp.example/'},
    'remote plaintext ws endpoint was accepted');
expectFailure({version: 1, endpoint: 'wss://user:pass@wisp.example/'},
    'endpoint credentials were accepted');
expectFailure({version: 1, endpoint: 'wss://wisp.example/?token=x'},
    'endpoint query credentials were accepted');
expectFailure({version: 1, endpoint: 'wss://wisp.example/', token: 'x'},
    'credential field was accepted');
expectFailure({version: 1, endpoint: 'wss://wisp.example/', extra: true},
    'unknown configuration field was accepted');
expectFailure({version: 2, endpoint: 'wss://wisp.example/'},
    'unsupported configuration version was accepted');
expectFailure({
  version: 1,
  endpoint: 'wss://wisp.example/',
  maxDataFrameBytes: 4096,
  maxWebSocketBufferedBytes: 4096,
}, 'WebSocket buffer that cannot hold a DATA packet was accepted');

console.log('M5_WISP_HOST_CONFIG:PASS');
""".replace("__HOST_URL__", json.dumps(HOST.resolve().as_uri()))
        completed = subprocess.run(
            [node, "--input-type=module", "--eval", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("M5_WISP_HOST_CONFIG:PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()

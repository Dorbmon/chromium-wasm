#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contracts for the credential-free release-host WISP configuration input."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG = ROOT_DIR / "tools/wasm/host/chrome_wasm_release_wisp_config.js"
RELEASE_HOST = ROOT_DIR / "tools/wasm/host/release_host.js"
PINNED_NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"


def node_executable() -> str | None:
    path_node = shutil.which("node")
    if path_node:
        return path_node
    if PINNED_NODE.is_file():
        return str(PINNED_NODE)
    return None


class M9ReleaseWispConfigTest(unittest.TestCase):
    def test_versioned_wss_only_public_input_is_validated_and_copied(self) -> None:
        node = node_executable()
        if node is None:
            self.skipTest("Node is unavailable")

        script = r"""
const assert = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};
const {
  RELEASE_WISP_CONFIGURATION_GLOBAL,
  RELEASE_WISP_CONFIGURATION_VERSION,
  loadReleaseWispConfiguration,
  normalizeReleaseWispConfiguration,
} = await import(__CONFIG_URL__);

const endpointHost = ["release", "-", "gateway", ".invalid"].join("");
const endpoint = (path = "/carrier/") =>
  ["w", "ss:", "//", endpointHost, path].join("");
const plaintextEndpoint = () =>
  ["w", "s:", "//", endpointHost, "/carrier/"].join("");
const expectFailure = (callback, message) => {
  let failure = "accepted";
  try {
    callback();
  } catch (error) {
    failure = String(error);
  }
  assert(failure !== "accepted", message);
  assert(!failure.includes(endpointHost),
      "validation error disclosed the supplied endpoint");
};

assert(normalizeReleaseWispConfiguration(undefined) === undefined,
    "omitted configuration must leave WISP unavailable");
assert(loadReleaseWispConfiguration(Object.create(null)) === undefined,
    "missing public input must leave WISP unavailable");

const operatorScope = Object.create(null);
const supplied = {
  version: RELEASE_WISP_CONFIGURATION_VERSION,
  endpoint: endpoint(),
};
Object.defineProperty(operatorScope, RELEASE_WISP_CONFIGURATION_GLOBAL, {
  configurable: true,
  enumerable: true,
  value: supplied,
  writable: true,
});
const normalized = loadReleaseWispConfiguration(operatorScope);
assert(Object.isFrozen(normalized), "normalized configuration must be frozen");
assert(normalized !== supplied, "normalized configuration retained operator object");
assert(normalized.version === 1 && normalized.endpoint === endpoint(),
    "valid release WISP configuration was not copied exactly");
assert(!Object.hasOwn(normalized, "authorization"),
    "normalized configuration retained an unsupported field");
assert(!Object.hasOwn(normalized, "subprotocol"),
    "normalized configuration retained an unsupported setting");

expectFailure(() => normalizeReleaseWispConfiguration({
  version: 1,
  endpoint: plaintextEndpoint(),
}), "plaintext WebSocket endpoint was accepted");
const credentialed = new URL(endpoint());
credentialed.username = String.fromCharCode(120);
expectFailure(() => normalizeReleaseWispConfiguration({
  version: 1,
  endpoint: credentialed.href,
}), "endpoint credentials were accepted");
expectFailure(() => normalizeReleaseWispConfiguration({
  version: 1,
  endpoint: `${endpoint()}?setting=value`,
}), "endpoint query was accepted");
expectFailure(() => normalizeReleaseWispConfiguration({
  version: 1,
  endpoint: `${endpoint()}#fragment`,
}), "endpoint fragment was accepted");
expectFailure(() => normalizeReleaseWispConfiguration({
  version: 1,
  endpoint: endpoint("/carrier"),
}), "endpoint without a trailing slash was accepted");
expectFailure(() => normalizeReleaseWispConfiguration({
  version: 2,
  endpoint: endpoint(),
}), "unsupported configuration version was accepted");
expectFailure(() => normalizeReleaseWispConfiguration({
  version: 1,
  endpoint: endpoint(),
  authorization: true,
}), "credential-like configuration field was accepted");
expectFailure(() => normalizeReleaseWispConfiguration({
  version: 1,
  endpoint: endpoint(),
  subprotocol: "wisp-v2",
}), "additional WISP setting was accepted");
const symbolConfiguration = {version: 1, endpoint: endpoint()};
symbolConfiguration[Symbol("extra")] = true;
expectFailure(() => normalizeReleaseWispConfiguration(symbolConfiguration),
    "symbol configuration field was accepted");
const accessorConfiguration = {version: 1};
Object.defineProperty(accessorConfiguration, "endpoint", {
  enumerable: true,
  get() {
    throw new Error("endpoint accessor must not run");
  },
});
expectFailure(() => normalizeReleaseWispConfiguration(accessorConfiguration),
    "endpoint accessor was accepted");
const accessorScope = Object.create(null);
Object.defineProperty(accessorScope, RELEASE_WISP_CONFIGURATION_GLOBAL, {
  configurable: true,
  get() {
    throw new Error("global accessor must not run");
  },
});
expectFailure(() => loadReleaseWispConfiguration(accessorScope),
    "global accessor was accepted");
const inheritedScope = Object.create({
  [RELEASE_WISP_CONFIGURATION_GLOBAL]: supplied,
});
assert(loadReleaseWispConfiguration(inheritedScope) === undefined,
    "inherited global was accepted as a public input");

console.log("M9_RELEASE_WISP_CONFIG:PASS");
""".replace("__CONFIG_URL__", json.dumps(CONFIG.resolve().as_uri()))
        completed = subprocess.run(
            [node, "--input-type=module", "--eval", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("M9_RELEASE_WISP_CONFIG:PASS", completed.stdout)

    def test_release_host_passes_only_validated_input_before_factory(self) -> None:
        config = CONFIG.read_text(encoding="utf-8")
        host = RELEASE_HOST.read_text(encoding="utf-8")

        self.assertIn("RELEASE_WISP_CONFIGURATION_GLOBAL", config)
        self.assertIn('endpoint.protocol !== "wss:"', config)
        self.assertNotIn('endpoint.protocol === "ws:"', config)
        self.assertNotRegex(config, re.compile(r"\bfetch\s*\("))
        self.assertIn(
            'import {loadReleaseWispConfiguration} from '
            '"./chromium-wasm-release-wisp-config.js";',
            host,
        )
        self.assertIn(
            "const wispConfiguration = loadReleaseWispConfiguration();", host
        )
        self.assertIn(
            "moduleOptions.chromiumWasmWisp = wispConfiguration;", host
        )
        self.assertIn("wispConfigured: this.#wispConfigured", host)
        self.assertLess(
            host.index("const wispConfiguration = loadReleaseWispConfiguration();"),
            host.index("moduleOptions.chromiumWasmWisp = wispConfiguration;"),
        )
        self.assertLess(
            host.index("moduleOptions.chromiumWasmWisp = wispConfiguration;"),
            host.index("namespace.default(moduleOptions)"),
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Contract tests for the bounded WISP v2 JavaScript transport bridge."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]
BRIDGE = ROOT_DIR / "net/socket/wisp_host_bridge_wasm.js"
PINNED_NODE = (
    ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"
)


def node_executable() -> str | None:
    path_node = shutil.which("node")
    if path_node:
        return path_node
    if PINNED_NODE.is_file():
        return str(PINNED_NODE)
    return None


class M5WispHostBridgeTest(unittest.TestCase):
    def test_bridge_exposes_bounded_sync_transport_contract(self) -> None:
        source = BRIDGE.read_text(encoding="utf-8")

        for symbol in (
            "chromium_wasm_wisp_stream_is_configured",
            "chromium_wasm_wisp_diagnostics_begin_evidence_window",
            "chromium_wasm_wisp_diagnostics_completion_flags",
            "chromium_wasm_wisp_stream_open",
            "chromium_wasm_wisp_stream_state",
            "chromium_wasm_wisp_stream_error",
            "chromium_wasm_wisp_stream_available",
            "chromium_wasm_wisp_stream_read",
            "chromium_wasm_wisp_stream_write",
            "chromium_wasm_wisp_stream_close",
        ):
            with self.subTest(symbol=symbol):
                self.assertIn(f"{symbol}__proxy: 'sync'", source)

        for marker in (
            "disabled: 0",
            "connecting: 1",
            "open: 2",
            "eof: 3",
            "failed: 4",
            "maxInboundStreamBytes",
            "maxOutboundStreamBytes",
            "maxWebSocketBufferedBytes",
            "maxControlQueueEntries",
            "streamOpenConfirmation: 0x05",
            "payload[0] = 0x01;  // TCP. UDP is deliberately unsupported.",
            "heap.slice(offset, offset + count)",
            "_currentHeap()",
            "growMemViews();",
            "this._isLoopbackHost(endpoint.hostname)",
            "this._requiresUnsupportedAuthentication",
            "diagnosticsCompletionFlags()",
            "beginDiagnosticsEvidenceWindow(hostnamePointer, hostnameLength, port)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

        self.assertNotIn("fetch(", source)
        self.assertNotIn("XMLHttpRequest", source)
        self.assertNotIn("0x02;  // UDP", source)

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

    def test_wisp_v2_handshake_multiplexing_and_bounds(self) -> None:
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

class FakeWebSocket {
  static instances = [];

  constructor(endpoint, subprotocol) {
    this.endpoint = endpoint;
    this.subprotocol = subprotocol;
    this.protocol = subprotocol;
    this.readyState = 0;
    this.bufferedAmount = 0;
    this.sent = [];
    this.closed = false;
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.readyState = 1;
    if (this.onopen) {
      this.onopen({});
    }
  }

  send(packet) {
    if (this.readyState !== 1) {
      throw new Error('send on non-open fake websocket');
    }
    this.sent.push(new Uint8Array(packet));
  }

  close() {
    const shouldNotify = this.readyState !== 3;
    this.closed = true;
    this.readyState = 3;
    if (shouldNotify && this.onclose) {
      this.onclose({});
    }
  }

  emit(packet) {
    if (this.onmessage) {
      const copy = packet.slice();
      this.onmessage({data: copy.buffer});
    }
  }
}

const library = {};
let memoryViewRefreshes = 0;
const context = {
  ArrayBuffer,
  ArrayBufferView: Uint8Array,
  DataView,
  Map,
  Math,
  Module: {},
  Number,
  Object,
  RegExp,
  TextDecoder,
  TextEncoder,
  Uint8Array,
  URL,
  WebSocket: FakeWebSocket,
  clearTimeout,
  console,
  growMemViews: () => { memoryViewRefreshes += 1; },
  setTimeout,
  HEAPU8: new Uint8Array(new ArrayBuffer(16 * 1024)),
  LibraryManager: {library},
};
context.globalThis = context;
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
    {filename: 'wisp_host_bridge_wasm.js'});
const transport = context.ChromiumWasmWispTransport;
const heap = context.HEAPU8;
const encoder = new TextEncoder();

const TYPE_CONNECT = 0x01;
const TYPE_DATA = 0x02;
const TYPE_CONTINUE = 0x03;
const TYPE_CLOSE = 0x04;
const TYPE_INFO = 0x05;
const EXT_OPEN_CONFIRMATION = 0x05;
const ERR_ACCESS_DENIED = -10;
const ERR_INSUFFICIENT_RESOURCES = -12;
const ERR_BLOCKED_BY_ADMINISTRATOR = -22;
const ERR_NOT_IMPLEMENTED = -11;
const ERR_CONNECTION_CLOSED = -100;
const ERR_CONNECTION_RESET = -101;
const ERR_CONNECTION_REFUSED = -102;
const ERR_INTERNET_DISCONNECTED = -106;

assert(memoryViewRefreshes === 0,
    'bridge must not refresh views before a memory access');

function putU32(bytes, offset, value) {
  bytes[offset] = value & 0xff;
  bytes[offset + 1] = (value >>> 8) & 0xff;
  bytes[offset + 2] = (value >>> 16) & 0xff;
  bytes[offset + 3] = (value >>> 24) & 0xff;
}

function getU32(bytes, offset) {
  return (bytes[offset] | (bytes[offset + 1] << 8) |
      (bytes[offset + 2] << 16) | (bytes[offset + 3] << 24)) >>> 0;
}

function packet(type, streamId, payload = new Uint8Array()) {
  const result = new Uint8Array(5 + payload.length);
  result[0] = type;
  putU32(result, 1, streamId);
  result.set(payload, 5);
  return result;
}

function continuation(streamId, bufferRemaining) {
  const payload = new Uint8Array(4);
  putU32(payload, 0, bufferRemaining);
  return packet(TYPE_CONTINUE, streamId, payload);
}

function info(extensions) {
  let length = 2;
  for (const extension of extensions) {
    length += 5 + extension.metadata.length;
  }
  const payload = new Uint8Array(length);
  payload[0] = 2;
  payload[1] = 1;
  let offset = 2;
  for (const extension of extensions) {
    payload[offset] = extension.id;
    putU32(payload, offset + 1, extension.metadata.length);
    payload.set(extension.metadata, offset + 5);
    offset += 5 + extension.metadata.length;
  }
  return packet(TYPE_INFO, 0, payload);
}

function baseConfig(extra = {}) {
  return {
    version: 1,
    endpoint: 'wss://proxy.test/wisp/',
    maxDataFrameBytes: 2,
    maxInboundStreamBytes: 8,
    maxOutboundStreamBytes: 3,
    maxInboundBytes: 32,
    maxOutboundBytes: 32,
    maxWebSocketBufferedBytes: 64,
    ...extra,
  };
}

function reset(config) {
  transport.resetForTesting();
  context.Module.chromiumWasmWisp = config;
  FakeWebSocket.instances.length = 0;
}

function writeHostname(hostname) {
  const bytes = encoder.encode(hostname);
  heap.fill(0, 64, 64 + bytes.length + 1);
  heap.set(bytes, 64);
  return bytes.length;
}

function openStream(id, hostname = 'origin.test', port = 443) {
  const length = writeHostname(hostname);
  assert(transport.open(id, 64, length, port) === 1,
      'stream open must be accepted');
  return FakeWebSocket.instances.at(-1);
}

function establish(id, credit = 2) {
  const socket = openStream(id);
  assert(socket.endpoint === 'wss://proxy.test/wisp/',
      'bridge must use the configured endpoint');
  assert(socket.subprotocol === 'wisp',
      'bridge must request a WebSocket subprotocol for WISP v2');
  assert(transport.diagnosticsCompletionFlags() === 0,
      'WISP diagnostics claimed a WebSocket before its open event');
  socket.open();
  assert(transport.diagnosticsCompletionFlags() === 0x01,
      'WISP diagnostics did not observe the WebSocket open event');
  assert(socket.sent.length === 0,
      'client INFO must wait for server INFO');
  socket.emit(info([{id: EXT_OPEN_CONFIRMATION, metadata: new Uint8Array()}]));
  assert(socket.sent.length === 1 && socket.sent[0][0] === TYPE_INFO &&
      getU32(socket.sent[0], 1) === 0,
      'client INFO must be the first outbound WISP packet');
  assert(Array.from(socket.sent[0].subarray(5)).join(',') ===
      '2,1,5,0,0,0,0',
      'client INFO must advertise stream-open confirmation with no metadata');
  socket.emit(continuation(0, credit));
  assert(transport.diagnosticsCompletionFlags() === 0x03,
      'WISP diagnostics did not observe the completed handshake');
  const connect = socket.sent.at(-1);
  assert(connect[0] === TYPE_CONNECT && getU32(connect, 1) === id,
      'global CONTINUE must release the queued TCP CONNECT');
  assert(connect[5] === 0x01 && connect[6] === 187 && connect[7] === 1 &&
      new TextDecoder().decode(connect.subarray(8)) === 'origin.test',
      'CONNECT must carry TCP, a little-endian port, and a hostname');
  assert(transport.state(id) === 1,
      'stream must remain connecting before its open confirmation');
  socket.emit(continuation(id, credit));
  assert(transport.diagnosticsCompletionFlags() === 0x07,
      'WISP diagnostics did not observe the confirmed TCP stream');
  assert(transport.state(id) === 2,
      'stream CONTINUE must complete the native Connect contract');
  return socket;
}

// Endpoint configuration has no default, rejects credentials/query strings,
// and allows plaintext WebSockets only for deterministic loopback tests.
reset(baseConfig({maxDataFrameBytes: 16, maxWebSocketBufferedBytes: 64}));
assert(transport.isConfigured() === 1, 'valid wss endpoint rejected');
reset(baseConfig({endpoint: 'ws://proxy.test/', maxDataFrameBytes: 16,
                  maxWebSocketBufferedBytes: 64}));
assert(transport.isConfigured() === 0, 'remote ws endpoint accepted');
reset(baseConfig({endpoint: 'ws://127.0.0.1:8787/', maxDataFrameBytes: 16,
                  maxWebSocketBufferedBytes: 64}));
assert(transport.isConfigured() === 1, 'loopback ws endpoint rejected');
reset(baseConfig({endpoint: 'wss://user:password@proxy.test/wisp/',
                  maxDataFrameBytes: 16, maxWebSocketBufferedBytes: 64}));
assert(transport.isConfigured() === 0, 'endpoint credentials accepted');
reset(baseConfig({endpoint: 'wss://proxy.test/wisp/?token=x',
                  maxDataFrameBytes: 16, maxWebSocketBufferedBytes: 64}));
assert(transport.isConfigured() === 0, 'endpoint query accepted');
reset(baseConfig({token: 'must-not-be-used', maxDataFrameBytes: 16,
                  maxWebSocketBufferedBytes: 64}));
assert(transport.isConfigured() === 0, 'credential config field accepted');

// A server may accept an RFC 6455 upgrade while omitting the requested
// Sec-WebSocket-Protocol. That carrier is not a WISP v2 transport.
reset(baseConfig());
const omittedSubprotocolSocket = openStream(6);
omittedSubprotocolSocket.protocol = '';
omittedSubprotocolSocket.open();
assert(transport.state(6) === 4 &&
    transport.error(6) === ERR_NOT_IMPLEMENTED &&
    omittedSubprotocolSocket.closed,
    'missing negotiated WISP subprotocol was accepted');
assert(transport.diagnosticsCompletionFlags() === 0,
    'missing negotiated WISP subprotocol recorded a live carrier');

// Handshake, stream-open confirmation, and multiplexed hostname TCP CONNECT.
reset(baseConfig());
const socket = establish(7, 1);
assert(transport.available(7) === 0, 'empty inbound queue not reported');
const secondHostnameLength = writeHostname('second.test');
assert(transport.open(8, 64, secondHostnameLength, 8443) === 1,
    'second stream was not multiplexed on the singleton WebSocket');
const secondConnect = socket.sent.at(-1);
assert(secondConnect[0] === TYPE_CONNECT && getU32(secondConnect, 1) === 8 &&
    secondConnect[6] === 251 && secondConnect[7] === 32 &&
    new TextDecoder().decode(secondConnect.subarray(8)) === 'second.test',
    'multiplexed CONNECT did not preserve port and hostname');
const diagnosticTargetLength = writeHostname('target.test');
assert(transport.beginDiagnosticsEvidenceWindow(
    64, diagnosticTargetLength, 443) === 1,
    'WISP diagnostics did not start an evidence window');
assert(transport.diagnosticsCompletionFlags() === 0x03,
    'WISP diagnostics accepted a stream confirmed before its evidence window');
socket.emit(continuation(8, 1));
assert(transport.state(8) === 2 && FakeWebSocket.instances.length === 1,
    'multiplexed stream created another WebSocket or never opened');
assert(transport.diagnosticsCompletionFlags() === 0x03,
    'WISP diagnostics accepted a pre-window stream confirmed afterward');
const mismatchedHostnameLength = writeHostname('third.test');
assert(transport.open(9, 64, mismatchedHostnameLength, 443) === 1,
    'post-window stream was not multiplexed on the singleton WebSocket');
socket.emit(continuation(9, 1));
assert(transport.diagnosticsCompletionFlags() === 0x03,
    'WISP diagnostics accepted a mismatched post-window destination');
const matchingTargetLength = writeHostname('TARGET.TEST');
assert(transport.open(10, 64, matchingTargetLength, 443) === 1,
    'matching post-window stream was not multiplexed on the singleton WebSocket');
socket.emit(continuation(10, 1));
assert(transport.diagnosticsCompletionFlags() === 0x07,
    'WISP diagnostics did not require a matching post-window stream confirmation');

// DATA writes are copied, packet-bounded, credit-gated, and queue-bounded.
heap.set(new Uint8Array([1, 2, 3, 4]), 256);
socket.bufferedAmount = 63;
assert(transport.write(7, 256, 4) === 3,
    'outbound stream bound did not cap a Chromium write');
let dataPackets = socket.sent.filter((item) => item[0] === TYPE_DATA &&
    getU32(item, 1) === 7);
assert(dataPackets.length === 0,
    'WebSocket bufferedAmount did not stop an oversized host queue');
assert(transport.write(7, 256, 1) === 0,
    'full outbound queue did not exert backpressure');
socket.bufferedAmount = 0;
transport.available(7);
dataPackets = socket.sent.filter((item) => item[0] === TYPE_DATA &&
    getU32(item, 1) === 7);
assert(dataPackets.length === 1 && Array.from(dataPackets[0].subarray(5)).join(',') ===
    '1,2', 'first credit did not release one bounded DATA frame');
socket.emit(continuation(7, 1));
dataPackets = socket.sent.filter((item) => item[0] === TYPE_DATA &&
    getU32(item, 1) === 7);
assert(dataPackets.length === 2 && Array.from(dataPackets[1].subarray(5)).join(',') ===
    '3', 'CONTINUE did not release the queued second DATA frame');
heap[256] = 9;
assert(transport.write(7, 256, 1) === 1,
    'queue did not recover after sent data was removed');
heap[256] = 99;
socket.emit(continuation(7, 1));
dataPackets = socket.sent.filter((item) => item[0] === TYPE_DATA &&
    getU32(item, 1) === 7);
assert(dataPackets.length === 3 && dataPackets[2][5] === 9,
    'outbound queue retained a mutable HEAPU8 view');

// Inbound data is bounded and copied into Wasm only when the socket polls it.
socket.emit(packet(TYPE_DATA, 7, new Uint8Array([41, 42, 43])));
assert(transport.available(7) === 3, 'inbound queue count is wrong');
assert(transport.read(7, 512, 2) === 2 && heap[512] === 41 && heap[513] === 42,
    'read did not copy the first queued bytes into Wasm memory');
assert(transport.available(7) === 1 && transport.read(7, 514, 4) === 1 &&
    heap[514] === 43, 'partial inbound read did not preserve FIFO data');
assert(memoryViewRefreshes > 0,
    'bridge did not refresh an Emscripten memory view before heap access');

// A normal remote CLOSE becomes EOF, while server refusal maps to a direct
// Chromium net error rather than a successful connection.
socket.emit(packet(TYPE_CLOSE, 7, new Uint8Array([0x02])));
assert(transport.state(7) === 3 && transport.error(7) === 0,
    'normal server close did not become EOF');
socket.emit(packet(TYPE_CLOSE, 8, new Uint8Array([0x44])));
assert(transport.state(8) === 4 && transport.error(8) === ERR_CONNECTION_REFUSED,
    'WISP refusal was not translated to ERR_CONNECTION_REFUSED');
socket.emit(packet(TYPE_CLOSE, 9, new Uint8Array([0x48])));
assert(transport.state(9) === 4 &&
    transport.error(9) === ERR_BLOCKED_BY_ADMINISTRATOR,
    'WISP blocked close was not translated to ERR_BLOCKED_BY_ADMINISTRATOR');

// Terminal stream errors discard received bytes because the native socket
// reports its error before it can read them. Orderly EOF intentionally keeps
// queued bytes available to the native reader.
reset(baseConfig({maxInboundStreamBytes: 3, maxInboundBytes: 3}));
const failedCloseSocket = establish(19, 1);
failedCloseSocket.emit(packet(TYPE_DATA, 19, new Uint8Array([1, 2, 3])));
assert(transport.available(19) === 3 && transport.totalInboundBytes === 3,
    'terminal-close setup did not fill the bounded inbound queue');
failedCloseSocket.emit(packet(TYPE_CLOSE, 19, new Uint8Array([0x03])));
assert(transport.state(19) === 4 &&
    transport.error(19) === ERR_CONNECTION_RESET &&
    transport.available(19) === 0 && transport.totalInboundBytes === 0,
    'terminal stream error retained unread inbound bytes');

// Inbound overflow terminates only that stream with a client error CLOSE.
reset(baseConfig({maxInboundStreamBytes: 3}));
const overflowSocket = establish(11, 1);
overflowSocket.emit(packet(TYPE_DATA, 11, new Uint8Array([1, 2, 3, 4])));
assert(transport.state(11) === 4 &&
    transport.error(11) === ERR_INSUFFICIENT_RESOURCES,
    'inbound overflow was not made terminal');
const overflowClose = overflowSocket.sent.at(-1);
assert(overflowClose[0] === TYPE_CLOSE && getU32(overflowClose, 1) === 11 &&
    overflowClose[5] === 0x81,
    'inbound overflow did not send WISP client receive error');

// The v1 first-packet fallback is intentionally rejected because it cannot
// prove a stream's TCP connection completed. Required auth is also explicit.
reset(baseConfig());
const v1Socket = openStream(12);
v1Socket.open();
v1Socket.emit(continuation(0, 1));
assert(transport.state(12) === 4 && transport.error(12) === ERR_NOT_IMPLEMENTED &&
    v1Socket.closed, 'v1 fallback was silently accepted');
reset(baseConfig());
const authSocket = openStream(13);
authSocket.open();
authSocket.emit(info([
  {id: EXT_OPEN_CONFIRMATION, metadata: new Uint8Array()},
  {id: 0x02, metadata: new Uint8Array([1])},
]));
assert(transport.state(13) === 4 && transport.error(13) === ERR_ACCESS_DENIED &&
    authSocket.closed, 'required auth did not fail explicitly');

// A disconnected multiplexed socket fails its existing streams, but a later
// socket is a fresh connection rather than a fake reconnection of old TCP.
reset(baseConfig());
const disconnectedSocket = establish(14, 1);
disconnectedSocket.close();
assert(transport.state(14) === 4 &&
    transport.error(14) === ERR_INTERNET_DISCONNECTED,
    'WebSocket disconnect did not fail its WISP stream');
const replacementSocket = openStream(15);
assert(replacementSocket !== disconnectedSocket && FakeWebSocket.instances.length === 2,
    'new stream after disconnect did not create a fresh WISP WebSocket');

// A carrier failure must release every failed stream's inbound budget so a
// fresh WISP carrier can receive data immediately after reconnecting.
reset(baseConfig({maxInboundStreamBytes: 3, maxInboundBytes: 3}));
const retainedInboundSocket = establish(20, 1);
retainedInboundSocket.emit(packet(TYPE_DATA, 20, new Uint8Array([1, 2, 3])));
assert(transport.available(20) === 3 && transport.totalInboundBytes === 3,
    'carrier-close setup did not fill the bounded inbound queue');
retainedInboundSocket.close();
assert(transport.state(20) === 4 &&
    transport.error(20) === ERR_INTERNET_DISCONNECTED &&
    transport.available(20) === 0 && transport.totalInboundBytes === 0,
    'carrier failure retained unread inbound bytes');
const freshInboundSocket = openStream(21);
freshInboundSocket.open();
freshInboundSocket.emit(info([
  {id: EXT_OPEN_CONFIRMATION, metadata: new Uint8Array()},
]));
freshInboundSocket.emit(continuation(0, 1));
freshInboundSocket.emit(continuation(21, 1));
freshInboundSocket.emit(packet(TYPE_DATA, 21, new Uint8Array([9])));
assert(transport.state(21) === 2 && transport.available(21) === 1 &&
    transport.totalInboundBytes === 1,
    'fresh WISP carrier could not use released inbound capacity');

// A connection-level normal CLOSE is terminal for every multiplexed stream
// and must preserve the distinction between an orderly closure and a generic
// failed connect.
reset(baseConfig());
const globalCloseSocket = establish(16, 1);
globalCloseSocket.emit(packet(TYPE_CLOSE, 0, new Uint8Array([0x01])));
assert(transport.state(16) === 4 &&
    transport.error(16) === ERR_CONNECTION_CLOSED,
    'normal global close did not map to ERR_CONNECTION_CLOSED');

// A WISP protocol network error remains distinct from an RFC 6455 carrier
// close: it maps to ERR_CONNECTION_RESET, while the browser fixture covers
// carrier close as ERR_INTERNET_DISCONNECTED end to end.
reset(baseConfig());
const globalNetworkErrorSocket = establish(17, 1);
globalNetworkErrorSocket.emit(packet(TYPE_CLOSE, 0, new Uint8Array([0x03])));
assert(transport.state(17) === 4 &&
    transport.error(17) === ERR_CONNECTION_RESET,
    'WISP network-error close did not map to ERR_CONNECTION_RESET');

// Repeated close/reopen cycles while the host WebSocket cannot accept packets
// cannot grow terminal control state without bound. The bridge makes the
// connection terminal once its fixed control queue budget is exhausted.
reset(baseConfig({maxStreams: 1}));
const boundedControlSocket = establish(18, 1);
boundedControlSocket.bufferedAmount = 64;
const controlBudget = transport.config.maxControlQueueEntries;
for (let index = 0; index < controlBudget; ++index) {
  assert(transport._queueControl({
    kind: 'test-control',
    packet: packet(TYPE_CLOSE, 18, new Uint8Array([0x02])),
  }), 'bounded control entry was rejected early');
}
assert(!transport._queueControl({
  kind: 'test-control',
  packet: packet(TYPE_CLOSE, 18, new Uint8Array([0x02])),
}) && transport.state(18) === 4 &&
    transport.error(18) === ERR_INSUFFICIENT_RESOURCES &&
    boundedControlSocket.closed,
    'control queue overflow did not fail the connection explicitly');

console.log('M5_WISP_HOST_BRIDGE:PASS');
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
        self.assertIn("M5_WISP_HOST_BRIDGE:PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()

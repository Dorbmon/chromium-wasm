#!/usr/bin/env node
// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

"use strict";

// This is a deliberately small, loopback-only test relay. It is not a WISP
// gateway implementation and must never be deployed as one. Its narrow
// destination allowlist lets the M5 browser smoke prove that Chromium's TLS,
// HTTP/1.1, HTTP/2, CORS, and WebSocket stacks use WISP TCP streams without
// making the test fixture an SSRF-capable proxy.

import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import http2 from "node:http2";
import https from "node:https";
import net from "node:net";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {TextDecoder} from "node:util";

const LOOPBACK_HOST = "127.0.0.1";
const FIXTURE = "chromium-wasm-m5-network-v1";
const WISP_PATH = "/wisp/";
const STATUS_PATH = "/status";
const TEST_HOSTNAME = "a.test";
// The controlled local-gateway proof deliberately presents an ordinary
// HTTPS authority to Chromium while keeping the actual target listener on an
// ephemeral loopback port. The relay owns this exact logical-destination
// mapping; it never forwards an arbitrary a.test port.
const LOCAL_GATEWAY_HTTPS_PORT = 443;
const LOCAL_GATEWAY_BLOCKED_PORT = 444;
const LOCAL_GATEWAY_PROBE_BODY = "M5_LOCAL_GATEWAY_443_OK";
const RESERVED_LOGICAL_PORTS = new Set([
  LOCAL_GATEWAY_HTTPS_PORT,
  LOCAL_GATEWAY_BLOCKED_PORT,
]);
const MAX_LOOPBACK_LISTEN_ATTEMPTS = 8;
const REDIRECT_COOKIE_NAME = "m5_redirect";
const CACHE_REVALIDATE_ETAG = '"m5-cache-revalidate-v1"';
const CACHE_REVALIDATE_BODY = "M5_CACHE_REVALIDATE_OK";
const CACHE_REVALIDATE_CACHE_CONTROL = "private, max-age=60, must-revalidate";
const CANCEL_STREAM_FIRST_CHUNK = "M5_CANCEL_STREAM_FIRST_CHUNK";
const CANCEL_STREAM_PROOF_BODY = "M5_CANCEL_STREAM_PROOF";
// Keep the fixture stages ASCII and short. The page consumes exact byte
// sequences through a ReadableStream reader before it is allowed to release
// the next producer stage.
const SLOW_STREAM_STAGES = Object.freeze([
  "M5_SLOW_STREAM_FIRST_STAGE",
  "M5_SLOW_STREAM_SECOND_STAGE",
  "M5_SLOW_STREAM_THIRD_STAGE",
]);
const SLOW_STREAM_FIRST_STAGE_ACK_BODY = "M5_SLOW_STREAM_FIRST_STAGE_ACK";
const SLOW_STREAM_SECOND_STAGE_ACK_BODY = "M5_SLOW_STREAM_SECOND_STAGE_ACK";
const SLOW_STREAM_PROOF_BODY = "M5_SLOW_STREAM_PROOF";
const SLOW_STREAM_CONSUMER_PAUSE_READY_BODY =
    "M5_SLOW_STREAM_CONSUMER_PAUSE_READY";
const SLOW_STREAM_CONSUMER_RESUME_BODY =
    "M5_SLOW_STREAM_CONSUMER_RESUMED";
// This is deliberately larger than one WISP DATA payload (16 KiB) while
// remaining well below the configured one-megabyte inbound queue bound. The
// page pauses its Fetch reader while this deterministic body is delivered,
// then drains and validates every byte before the relay permits stage three.
const SLOW_STREAM_CONSUMER_BURST_BYTES = 64 * 1024;
const SLOW_STREAM_CONSUMER_BURST_BYTE = 0x53;  // ASCII "S".
// The large-download lane is intentionally well below the host bridge's
// one-megabyte per-stream inbound queue, while still requiring 32 complete
// WISP DATA payloads. Chromium must consume it as a byte stream; it is not a
// host fetch or a synthetic browser download completion.
const LARGE_DOWNLOAD_BYTES = 512 * 1024;
const LARGE_DOWNLOAD_CHUNK_BYTES = 16 * 1024;
const LARGE_DOWNLOAD_CHUNK_COUNT =
    LARGE_DOWNLOAD_BYTES / LARGE_DOWNLOAD_CHUNK_BYTES;
const LARGE_DOWNLOAD_CONTENT_DISPOSITION =
    'attachment; filename="m5-large-download.bin"';
// The multiplex lane holds one H2 and one cross-origin H1 response until the
// relay has privately correlated both target connections to distinct live WISP
// streams on its one already-open carrier.  The fixed bodies are intentionally
// small: the proof is stream overlap, not response throughput.
const MULTIPLEX_H2_BODY = "M5_WISP_MULTIPLEX_H2";
const MULTIPLEX_H1_BODY = "M5_WISP_MULTIPLEX_H1";
const MULTIPLEX_BARRIER_TIMEOUT_MS = 5 * 1000;
// Reconnect coverage deliberately terminates an already-delivered H2 body.
// The page must observe that partial stream fail, then make a separate
// recovery request on a fresh WISP WebSocket and H2 session. Keeping one byte
// unsent makes a clean EOF or a transparent replay an explicit test failure.
const RECONNECT_STREAM_FIRST_CHUNK = "M5_WISP_RECONNECT_FIRST_CHUNK";
const RECONNECT_STREAM_CONTENT_LENGTH =
    Buffer.byteLength(RECONNECT_STREAM_FIRST_CHUNK) + 1;
const RECONNECT_FIRST_CHUNK_ACK_BODY = "M5_WISP_RECONNECT_FIRST_CHUNK_ACK";
const RECONNECT_RECOVERY_BODY = "M5_WISP_RECONNECT_RECOVERY";
const RECONNECT_DISCONNECT_DELAY_MS = 100;
const RECONNECT_ACK_TIMEOUT_MS = 5000;
const RECONNECT_RECOVERY_TIMEOUT_MS = 5000;
const RECONNECT_STREAM_FAILURE_TIMEOUT_MS = 5000;

const WISP_PACKET_TYPES = Object.freeze({
  CONNECT: 0x01,
  DATA: 0x02,
  CONTINUE: 0x03,
  CLOSE: 0x04,
  INFO: 0x05,
});
const WISP_CLOSE_REASONS = Object.freeze({
  VOLUNTARY: 0x02,
  NETWORK_ERROR: 0x03,
  INCOMPATIBLE_EXTENSIONS: 0x04,
  INVALID_STREAM: 0x41,
  UNREACHABLE: 0x42,
  STREAM_TIMED_OUT: 0x43,
  REFUSED: 0x44,
  BLOCKED: 0x48,
  THROTTLED: 0x49,
});
const WISP_STREAM_OPEN_CONFIRMATION_EXTENSION = 0x05;

const MAX_WEBSOCKET_FRAME_BYTES = 1024 * 1024 + 5;
const MAX_WEBSOCKET_MESSAGE_BYTES = 1024 * 1024 + 5;
const MAX_WEBSOCKET_RAW_BUFFER_BYTES = MAX_WEBSOCKET_FRAME_BYTES + 14;
const MAX_STREAMS_PER_RELAY = 64;
const MAX_STREAM_INGRESS_BYTES = 1024 * 1024;
const MAX_GLOBAL_INGRESS_BYTES = 8 * 1024 * 1024;
const MAX_GLOBAL_INGRESS_FRAMES = 1024;
const MAX_STREAM_EGRESS_BYTES = 1024 * 1024;
const MAX_GLOBAL_EGRESS_BYTES = 8 * 1024 * 1024;
const MAX_WISP_DATA_PAYLOAD_BYTES = 16 * 1024;
const MAX_ECHO_MESSAGE_BYTES = 4096;
const STREAM_PACKET_CREDIT = 64;
const GLOBAL_PACKET_CREDIT = 1024;
const MAX_TRANSCRIPT_ENTRIES = 256;
// Test counters are compact evidence rather than request logs. Keep them
// saturating so a loopback client cannot make status output unbounded.
const MAX_TEST_COUNTER = 16;
const RELAY_HANDSHAKE_TIMEOUT_MS = 10 * 1000;
const DESTINATION_IDLE_TIMEOUT_MS = 30 * 1000;
const CANCEL_STREAM_PROOF_TIMEOUT_MS = 5 * 1000;
// Each later stage is deliberately scheduled only after the page has read
// and acknowledged the preceding stage on the same H2 session. The lower
// bound is separately recorded, rather than inferring slowness from page
// timers alone.
const SLOW_STREAM_STAGE_DELAY_MS = 150;
const SLOW_STREAM_STAGE_ACK_TIMEOUT_MS = 5 * 1000;

const REPOSITORY_ROOT = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)), "../..");
const TEST_CERTIFICATE_PATH = path.join(
    REPOSITORY_ROOT, "net/data/ssl/certificates/test_names.pem");
// This leaf chains to the same test root as |TEST_CERTIFICATE_PATH|, but its
// only DNS SAN is localhost. Serving it for an a.test WISP destination makes
// the M5 negative lane a deterministic hostname-validation failure rather
// than an untrusted-root or expired-certificate failure.
const TLS_FAILURE_CERTIFICATE_PATH = path.join(
    REPOSITORY_ROOT, "net/data/ssl/certificates/localhost_cert.pem");

function fail(message) {
  throw new Error(message);
}

function parseArguments(argv) {
  let hostOrigin = null;
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--host-origin") {
      if (hostOrigin !== null || index + 1 >= argv.length) {
        fail("--host-origin must be supplied exactly once");
      }
      hostOrigin = argv[++index];
      continue;
    }
    fail(`unsupported argument: ${argument}`);
  }
  if (hostOrigin === null) {
    fail("missing required --host-origin");
  }

  let parsed;
  try {
    parsed = new URL(hostOrigin);
  } catch (_) {
    fail("--host-origin must be an absolute http(s) origin");
  }
  if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
      parsed.username || parsed.password || parsed.search || parsed.hash ||
      (parsed.pathname !== "/" && parsed.pathname !== "")) {
    fail("--host-origin must be a credential-free http(s) origin");
  }
  return {hostOrigin: parsed.origin};
}

function listenLoopback(server) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const beginListen = () => {
      attempts += 1;
      const onError = (error) => {
        server.off("listening", onListening);
        reject(error);
      };
      const onListening = () => {
        server.off("error", onError);
        const address = server.address();
        if (!address || typeof address === "string" ||
            address.address !== LOOPBACK_HOST ||
            !Number.isSafeInteger(address.port) || address.port < 1 ||
            address.port > 65535) {
          reject(new Error("test server did not bind an IPv4 loopback port"));
          return;
        }
        if (!RESERVED_LOGICAL_PORTS.has(address.port)) {
          resolve(address.port);
          return;
        }
        server.close((error) => {
          if (error) {
            reject(error);
            return;
          }
          if (attempts >= MAX_LOOPBACK_LISTEN_ATTEMPTS) {
            reject(new Error("test server repeatedly selected a reserved port"));
            return;
          }
          beginListen();
        });
      };
      server.once("error", onError);
      server.once("listening", onListening);
      server.listen({host: LOOPBACK_HOST, port: 0, exclusive: true});
    };
    beginListen();
  });
}

function closeServer(server) {
  return new Promise((resolve) => {
    if (!server.listening) {
      resolve();
      return;
    }
    server.close(() => resolve());
  });
}

function websocketAcceptValue(key) {
  return crypto.createHash("sha1")
      .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
      .digest("base64");
}

function isValidWebSocketKey(key) {
  if (typeof key !== "string" ||
      !/^[A-Za-z0-9+/]{22}==$/.test(key)) {
    return false;
  }
  try {
    return Buffer.from(key, "base64").length === 16;
  } catch (_) {
    return false;
  }
}

function headerContainsToken(value, token) {
  return typeof value === "string" && value.split(",").some((candidate) =>
    candidate.trim().toLowerCase() === token.toLowerCase());
}

function websocketFrame(opcode, payload) {
  const data = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  if (data.length > MAX_WEBSOCKET_FRAME_BYTES) {
    fail("attempted to emit an oversized WebSocket frame");
  }
  let header;
  if (data.length <= 125) {
    header = Buffer.allocUnsafe(2);
    header[1] = data.length;
  } else if (data.length <= 0xffff) {
    header = Buffer.allocUnsafe(4);
    header[1] = 126;
    header.writeUInt16BE(data.length, 2);
  } else {
    header = Buffer.allocUnsafe(10);
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(data.length), 2);
  }
  header[0] = 0x80 | opcode;
  return Buffer.concat([header, data]);
}

function websocketClosePayload(code, reason) {
  const reasonBytes = Buffer.from(reason, "utf8").subarray(0, 123);
  const result = Buffer.allocUnsafe(2 + reasonBytes.length);
  result.writeUInt16BE(code, 0);
  reasonBytes.copy(result, 2);
  return result;
}

// A bounded RFC 6455 peer. Browser clients must mask every frame. The server
// accepts only binary messages for WISP and text/binary messages for the
// controlled inner-page echo endpoint.
class WebSocketPeer {
  constructor(socket, options) {
    this.socket = socket;
    this.allowText = options.allowText === true;
    this.onMessage = options.onMessage;
    this.onClosed = options.onClosed;
    this.onWritable = options.onWritable || (() => {});
    this.input = Buffer.alloc(0);
    this.fragmentOpcode = null;
    this.fragments = [];
    this.fragmentBytes = 0;
    this.inputPaused = false;
    this.backpressured = false;
    this.closed = false;
    this.closeSent = false;
    this.closeNotified = false;

    socket.on("data", (chunk) => this._receive(chunk));
    socket.on("drain", () => {
      this.backpressured = false;
      this.onWritable();
    });
    socket.on("error", () => this._notifyClosed());
    socket.on("close", () => this._notifyClosed());
  }

  receiveInitial(bytes) {
    if (bytes && bytes.length > 0) {
      this._receive(bytes);
    }
  }

  pauseInput() {
    if (!this.closed && !this.inputPaused) {
      this.inputPaused = true;
      this.socket.pause();
    }
  }

  resumeInput() {
    if (!this.closed && this.inputPaused) {
      this.inputPaused = false;
      this.socket.resume();
      this._parseInput();
    }
  }

  send(opcode, payload) {
    if (this.closed || this.backpressured) {
      return {accepted: false, blocked: true};
    }
    let frame;
    try {
      frame = websocketFrame(opcode, payload);
    } catch (_) {
      this.close(1009, "frame-too-large");
      return {accepted: false, blocked: true};
    }
    // Node buffers accepted writes internally. Put a hard ceiling on that
    // buffer rather than allowing a slow browser to make the test host grow.
    if (this.socket.writableLength + frame.length >
        MAX_GLOBAL_EGRESS_BYTES + MAX_WEBSOCKET_FRAME_BYTES) {
      this.close(1009, "outbound-limit");
      return {accepted: false, blocked: true};
    }
    const writable = this.socket.write(frame);
    if (!writable) {
      this.backpressured = true;
    }
    return {accepted: true, blocked: !writable};
  }

  sendBinary(payload) {
    return this.send(0x02, payload);
  }

  close(code = 1000, reason = "") {
    if (this.closed) {
      return;
    }
    if (!this.closeSent && this.socket.writable) {
      this.closeSent = true;
      try {
        this.socket.write(websocketFrame(0x08, websocketClosePayload(code, reason)));
      } catch (_) {
        // The socket is terminal either way.
      }
    }
    this.closed = true;
    this.socket.end();
    this._notifyClosed();
  }

  destroy() {
    if (!this.closed) {
      this.closed = true;
    }
    this.socket.destroy();
    this._notifyClosed();
  }

  _receive(chunk) {
    if (this.closed || !Buffer.isBuffer(chunk)) {
      return;
    }
    if (this.input.length + chunk.length > MAX_WEBSOCKET_RAW_BUFFER_BYTES) {
      this.close(1009, "input-limit");
      return;
    }
    this.input = this.input.length === 0 ? Buffer.from(chunk) :
      Buffer.concat([this.input, chunk]);
    this._parseInput();
  }

  _parseInput() {
    while (!this.closed && !this.inputPaused) {
      if (this.input.length < 2) {
        return;
      }
      const first = this.input[0];
      const second = this.input[1];
      const fin = (first & 0x80) !== 0;
      const rsv = first & 0x70;
      const opcode = first & 0x0f;
      const masked = (second & 0x80) !== 0;
      let payloadLength = second & 0x7f;
      let offset = 2;

      if (rsv !== 0 || !masked) {
        this.close(1002, "invalid-frame");
        return;
      }
      if (payloadLength === 126) {
        if (this.input.length < offset + 2) {
          return;
        }
        payloadLength = this.input.readUInt16BE(offset);
        offset += 2;
      } else if (payloadLength === 127) {
        if (this.input.length < offset + 8) {
          return;
        }
        const length = this.input.readBigUInt64BE(offset);
        if (length > BigInt(MAX_WEBSOCKET_FRAME_BYTES)) {
          this.close(1009, "frame-too-large");
          return;
        }
        payloadLength = Number(length);
        offset += 8;
      }
      if (payloadLength > MAX_WEBSOCKET_FRAME_BYTES) {
        this.close(1009, "frame-too-large");
        return;
      }
      if (this.input.length < offset + 4 + payloadLength) {
        return;
      }
      const mask = this.input.subarray(offset, offset + 4);
      offset += 4;
      const payload = Buffer.from(this.input.subarray(
          offset, offset + payloadLength));
      for (let index = 0; index < payload.length; index += 1) {
        payload[index] ^= mask[index % 4];
      }
      this.input = this.input.subarray(offset + payloadLength);

      if (opcode >= 0x08) {
        if (!fin || payloadLength > 125) {
          this.close(1002, "invalid-control");
          return;
        }
        if (opcode === 0x08) {
          if (payloadLength === 1) {
            this.close(1002, "invalid-close");
            return;
          }
          if (!this.closeSent && this.socket.writable) {
            this.closeSent = true;
            try {
              this.socket.write(websocketFrame(0x08, payload));
            } catch (_) {
              // Close below.
            }
          }
          this.closed = true;
          this.socket.end();
          this._notifyClosed();
          return;
        }
        if (opcode === 0x09) {
          this.send(0x0a, payload);
          continue;
        }
        if (opcode === 0x0a) {
          continue;
        }
        this.close(1002, "unknown-control");
        return;
      }

      if (opcode === 0x00) {
        if (this.fragmentOpcode === null) {
          this.close(1002, "unexpected-continuation");
          return;
        }
        if (!this._appendFragment(payload)) {
          return;
        }
        if (fin) {
          const messageOpcode = this.fragmentOpcode;
          const message = Buffer.concat(this.fragments, this.fragmentBytes);
          this.fragmentOpcode = null;
          this.fragments = [];
          this.fragmentBytes = 0;
          this._deliverMessage(messageOpcode, message);
        }
        continue;
      }

      if (opcode !== 0x01 && opcode !== 0x02) {
        this.close(1002, "unknown-data");
        return;
      }
      if (this.fragmentOpcode !== null) {
        this.close(1002, "overlapping-fragment");
        return;
      }
      if (fin) {
        this._deliverMessage(opcode, payload);
        continue;
      }
      this.fragmentOpcode = opcode;
      this.fragments = [];
      this.fragmentBytes = 0;
      if (!this._appendFragment(payload)) {
        return;
      }
    }
  }

  _appendFragment(payload) {
    if (this.fragmentBytes + payload.length > MAX_WEBSOCKET_MESSAGE_BYTES) {
      this.close(1009, "message-too-large");
      return false;
    }
    this.fragments.push(payload);
    this.fragmentBytes += payload.length;
    return true;
  }

  _deliverMessage(opcode, payload) {
    if (this.closed) {
      return;
    }
    if (opcode === 0x01) {
      if (!this.allowText) {
        this.close(1003, "binary-required");
        return;
      }
      try {
        new TextDecoder("utf-8", {fatal: true}).decode(payload);
      } catch (_) {
        this.close(1007, "invalid-utf8");
        return;
      }
    }
    try {
      this.onMessage({opcode, payload});
    } catch (_) {
      this.close(1011, "handler-failure");
    }
  }

  _notifyClosed() {
    if (this.closeNotified) {
      return;
    }
    this.closeNotified = true;
    this.onClosed();
  }
}

function rejectUpgrade(socket, status, message) {
  if (!socket.destroyed) {
    socket.write(
        `HTTP/1.1 ${status} ${message}\r\nConnection: close\r\n` +
        "Content-Length: 0\r\n\r\n");
    socket.destroy();
  }
}

function acceptWebSocketUpgrade(request, socket, head, options) {
  if (request.url !== options.path ||
      !headerContainsToken(request.headers.connection, "upgrade") ||
      String(request.headers.upgrade || "").toLowerCase() !== "websocket" ||
      request.headers["sec-websocket-version"] !== "13" ||
      !isValidWebSocketKey(request.headers["sec-websocket-key"]) ||
      request.headers.origin !== options.expectedOrigin) {
    rejectUpgrade(socket, 400, "Bad Request");
    return null;
  }

  let selectedSubprotocol = null;
  if (options.subprotocol) {
    if (!headerContainsToken(
        request.headers["sec-websocket-protocol"], options.subprotocol)) {
      rejectUpgrade(socket, 426, "Upgrade Required");
      return null;
    }
    selectedSubprotocol = options.subprotocol;
  }

  const responseHeaders = [
    "HTTP/1.1 101 Switching Protocols",
    "Upgrade: websocket",
    "Connection: Upgrade",
    `Sec-WebSocket-Accept: ${websocketAcceptValue(request.headers["sec-websocket-key"])}`,
  ];
  if (selectedSubprotocol) {
    responseHeaders.push(`Sec-WebSocket-Protocol: ${selectedSubprotocol}`);
  }
  socket.write(`${responseHeaders.join("\r\n")}\r\n\r\n`);
  const peer = new WebSocketPeer(socket, options);
  peer.receiveInitial(head);
  return peer;
}

function wispPacket(type, streamId, payload = Buffer.alloc(0)) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  if (!Number.isSafeInteger(streamId) || streamId < 0 ||
      streamId > 0xffffffff || body.length > MAX_WEBSOCKET_MESSAGE_BYTES - 5) {
    fail("invalid WISP packet");
  }
  const result = Buffer.allocUnsafe(5 + body.length);
  result[0] = type;
  result.writeUInt32LE(streamId, 1);
  body.copy(result, 5);
  return result;
}

function wispContinuePacket(streamId, credit) {
  const payload = Buffer.allocUnsafe(4);
  payload.writeUInt32LE(credit, 0);
  return wispPacket(WISP_PACKET_TYPES.CONTINUE, streamId, payload);
}

function wispClosePacket(streamId, reason) {
  return wispPacket(WISP_PACKET_TYPES.CLOSE, streamId, Buffer.from([reason]));
}

function serverInfoPacket() {
  // WISP v2.1 with the zero-length stream-open-confirmation extension.
  return wispPacket(WISP_PACKET_TYPES.INFO, 0, Buffer.from([
    2, 1,
    WISP_STREAM_OPEN_CONFIRMATION_EXTENSION, 0, 0, 0, 0,
  ]));
}

function isExpectedClientInfo(payload) {
  return payload.length === 7 && payload[0] === 2 && payload[1] === 1 &&
      payload[2] === WISP_STREAM_OPEN_CONFIRMATION_EXTENSION &&
      payload.readUInt32LE(3) === 0;
}

function decodeHostname(bytes) {
  if (bytes.length === 0 || bytes.length > 253) {
    return null;
  }
  try {
    const hostname = new TextDecoder("utf-8", {fatal: true}).decode(bytes);
    return hostname === TEST_HOSTNAME ? hostname : null;
  } catch (_) {
    return null;
  }
}

class Transcript {
  constructor() {
    this.entries = [];
    this.sequence = 0;
  }

  add(event, fields = {}) {
    const entry = {sequence: ++this.sequence, event};
    for (const [name, value] of Object.entries(fields)) {
      if (Number.isSafeInteger(value) && value >= 0 && value <= 0xffffffff) {
        entry[name] = value;
      } else if (typeof value === "boolean") {
        entry[name] = value;
      } else if (typeof value === "string" &&
                 /^[a-z0-9:/._-]{1,96}$/i.test(value)) {
        entry[name] = value;
      }
    }
    this.entries.push(entry);
    if (this.entries.length > MAX_TRANSCRIPT_ENTRIES) {
      this.entries.shift();
    }
  }

  snapshot() {
    return this.entries.map((entry) => ({...entry}));
  }
}

function appendRequestedDestination(context, hostname, port) {
  if (context.stats.requestedDestinations.length >= MAX_STREAMS_PER_RELAY) {
    return;
  }
  context.stats.requestedDestinations.push({hostname, port});
}

function destinationRouteKey(hostname, port) {
  return `${hostname}:${port}`;
}

function addDestinationRoute(context, hostname, logicalPort, connectPort,
                             kind) {
  if (hostname !== TEST_HOSTNAME ||
      !Number.isSafeInteger(logicalPort) || logicalPort < 1 ||
      logicalPort > 65535 || !Number.isSafeInteger(connectPort) ||
      connectPort < 1 || connectPort > 65535 ||
      typeof kind !== "string" || kind.length === 0) {
    fail("invalid loopback WISP destination route");
  }
  const key = destinationRouteKey(hostname, logicalPort);
  if (context.destinationRoutes.has(key)) {
    fail("duplicate loopback WISP destination route");
  }
  context.destinationRoutes.set(key, {
    connectHost: LOOPBACK_HOST,
    connectPort,
    kind,
  });
}

function incrementBoundedCounter(context, name) {
  context.stats[name] = Math.min(
      context.stats[name] + 1, MAX_TEST_COUNTER);
}

function statusSnapshot(context) {
  return {
    fixture: FIXTURE,
    protocol: 1,
    ready: true,
    activeWispSessions: context.relays.size,
    cacheConditionalRequests: context.stats.cacheConditionalRequests,
    cacheNotModified304s: context.stats.cacheNotModified304s,
    cacheStore200s: context.stats.cacheStore200s,
    cacheUnexpectedRequests: context.stats.cacheUnexpectedRequests,
    cancelStreamCancelResets: context.stats.cancelStreamCancelResets,
    cancelStreamFirstChunks: context.stats.cancelStreamFirstChunks,
    cancelStreamPhase: context.cancelStreamPhase,
    cancelStreamProofs: context.stats.cancelStreamProofs,
    cancelStreamProofSessionMismatches:
      context.stats.cancelStreamProofSessionMismatches,
    cancelStreamProofTimeouts: context.stats.cancelStreamProofTimeouts,
    cancelStreamRequests: context.stats.cancelStreamRequests,
    cancelStreamUnexpectedResets: context.stats.cancelStreamUnexpectedResets,
    cspConnectSrcProofs: context.stats.cspConnectSrcProofs,
    cspConnectSrcTargetRequests: context.stats.cspConnectSrcTargetRequests,
    cspConnectSrcTargetTcpConnections:
      context.stats.cspConnectSrcTargetTcpConnections,
    corsRequests: context.stats.corsRequests,
    h2Requests: {
      count: context.stats.h2Requests,
      protocol: "h2",
    },
    largeDownloadBackpressureEvents:
      context.stats.largeDownloadBackpressureEvents,
    largeDownloadBytes: context.stats.largeDownloadBytes,
    largeDownloadChunks: context.stats.largeDownloadChunks,
    largeDownloadCompletions: context.stats.largeDownloadCompletions,
    largeDownloadPhase: context.largeDownloadPhase,
    largeDownloadRequests: context.stats.largeDownloadRequests,
    largeDownloadUnexpectedCloses:
      context.stats.largeDownloadUnexpectedCloses,
    localGateway443Requests: context.stats.localGateway443Requests,
    localGateway443StreamsOpened: context.stats.localGateway443StreamsOpened,
    localGatewayBlockedPortAttempts:
      context.stats.localGatewayBlockedPortAttempts,
    multiplexBarrierReleases: context.stats.multiplexBarrierReleases,
    multiplexBarrierTimeouts: context.stats.multiplexBarrierTimeouts,
    multiplexBothStreamsOpen: context.stats.multiplexBothStreamsOpen,
    multiplexCorrelationFailures: context.stats.multiplexCorrelationFailures,
    multiplexDistinctWispStreamCount:
      context.stats.multiplexDistinctWispStreamCount,
    multiplexH1Requests: context.stats.multiplexH1Requests,
    multiplexH2Requests: context.stats.multiplexH2Requests,
    multiplexPhase: context.multiplexPhase,
    multiplexResponses: context.stats.multiplexResponses,
    multiplexSharedCarrier: context.stats.multiplexSharedCarrier,
    multiplexUnexpectedCloses: context.stats.multiplexUnexpectedCloses,
    mixedContentProofs: context.stats.mixedContentProofs,
    mixedContentTargetPostControlRequests:
      context.stats.mixedContentTargetPostControlRequests,
    mixedContentTargetPostControlTcpConnections:
      context.stats.mixedContentTargetPostControlTcpConnections,
    mixedContentTargetPostControlWispConnects:
      context.stats.mixedContentTargetPostControlWispConnects,
    plaintextHttpControlPhase: context.plaintextHttpControlPhase,
    plaintextHttpControlProofs: context.stats.plaintextHttpControlProofs,
    plaintextHttpControlRequests: context.stats.plaintextHttpControlRequests,
    plaintextHttpControlTcpConnections:
      context.stats.plaintextHttpControlTcpConnections,
    redirectCookieValidations: context.stats.redirectCookieValidations,
    redirectRequests: context.stats.redirectRequests,
    reconnectDisconnectRequests: context.stats.reconnectDisconnectRequests,
    reconnectFirstChunkAcks: context.stats.reconnectFirstChunkAcks,
    reconnectFirstChunks: context.stats.reconnectFirstChunks,
    reconnectPhase: context.reconnectPhase,
    reconnectRecoveryRequests: context.stats.reconnectRecoveryRequests,
    reconnectSessionMismatches: context.stats.reconnectSessionMismatches,
    reconnectStreamRequests: context.stats.reconnectStreamRequests,
    reconnectUnexpectedCloses: context.stats.reconnectUnexpectedCloses,
    reconnectUnexpectedRetries: context.stats.reconnectUnexpectedRetries,
    rejectedDestinations: context.stats.rejectedDestinations,
    relayErrors: context.stats.relayErrors,
    requestedDestinations: context.stats.requestedDestinations.map(
        (destination) => ({...destination})),
    slowStreamCompletedStreams: context.stats.slowStreamCompletedStreams,
    slowStreamConsumerBurstBytes: context.stats.slowStreamConsumerBurstBytes,
    slowStreamConsumerBurstWrites:
      context.stats.slowStreamConsumerBurstWrites,
    slowStreamConsumerPauseReadyRequests:
      context.stats.slowStreamConsumerPauseReadyRequests,
    slowStreamConsumerResumes: context.stats.slowStreamConsumerResumes,
    slowStreamFirstStageAcks: context.stats.slowStreamFirstStageAcks,
    slowStreamFirstStages: context.stats.slowStreamFirstStages,
    slowStreamPhase: context.slowStreamPhase,
    slowStreamSessionMismatches: context.stats.slowStreamSessionMismatches,
    slowStreamStageAckTimeouts: context.stats.slowStreamStageAckTimeouts,
    slowStreamProofs: context.stats.slowStreamProofs,
    slowStreamRequests: context.stats.slowStreamRequests,
    slowStreamSecondStageAcks: context.stats.slowStreamSecondStageAcks,
    slowStreamSecondStages: context.stats.slowStreamSecondStages,
    slowStreamStageDelayMs: context.slowStreamStageDelayMs,
    slowStreamStageDelaySchedules: context.stats.slowStreamStageDelaySchedules,
    slowStreamThirdStages: context.stats.slowStreamThirdStages,
    slowStreamUnexpectedCloses: context.stats.slowStreamUnexpectedCloses,
    tlsMismatchHttpStreams: context.stats.tlsMismatchHttpStreams,
    tlsMismatchTcpConnections: context.stats.tlsMismatchTcpConnections,
    udpPackets: context.stats.udpPackets,
    webSocketEchoes: context.stats.webSocketEchoes,
    wispSessions: context.stats.wispSessions,
    transcript: context.transcript.snapshot(),
  };
}

class WispRelay {
  constructor(peer, context, onClosed) {
    this.peer = peer;
    this.context = context;
    this.onClosed = onClosed;
    this.carrierId = context.nextCarrierId++;
    this.phase = "awaiting-info";
    this.streams = new Map();
    this.inboundFrames = 0;
    this.inboundBytes = 0;
    this.egressBytes = 0;
    this.closed = false;
    this.handshakeTimer = setTimeout(() => {
      if (this.phase !== "ready") {
        this._protocolFailure("handshake-timeout");
      }
    }, RELAY_HANDSHAKE_TIMEOUT_MS);
    this.handshakeTimer.unref?.();
    this.context.stats.wispSessions += 1;
    this.context.transcript.add("wisp-connected");
    this._sendPacket(serverInfoPacket());
  }

  receive(message) {
    if (this.closed) {
      return;
    }
    if (message.opcode !== 0x02 || message.payload.length < 5) {
      this._protocolFailure("binary-wisp-required");
      return;
    }
    const packet = message.payload;
    const type = packet[0];
    const streamId = packet.readUInt32LE(1);
    const payload = packet.subarray(5);
    switch (type) {
      case WISP_PACKET_TYPES.INFO:
        this._receiveInfo(streamId, payload);
        break;
      case WISP_PACKET_TYPES.CONNECT:
        this._receiveConnect(streamId, payload);
        break;
      case WISP_PACKET_TYPES.DATA:
        this._receiveData(streamId, payload);
        break;
      case WISP_PACKET_TYPES.CLOSE:
        this._receiveClose(streamId, payload);
        break;
      default:
        this._protocolFailure("unsupported-wisp-packet");
        break;
    }
  }

  writable() {
    if (!this.closed) {
      this._flushTargetOutput();
    }
  }

  close() {
    if (this.closed) {
      return;
    }
    this.closed = true;
    clearTimeout(this.handshakeTimer);
    for (const stream of [...this.streams.values()]) {
      this._removeStream(stream, {destroy: true});
    }
    this.context.transcript.add("wisp-disconnected");
    this.onClosed();
  }

  _receiveInfo(streamId, payload) {
    if (this.phase !== "awaiting-info" || streamId !== 0 ||
        !isExpectedClientInfo(payload)) {
      this._protocolFailure("invalid-info");
      return;
    }
    this.phase = "ready";
    clearTimeout(this.handshakeTimer);
    this.context.transcript.add("wisp-ready");
    this._sendPacket(wispContinuePacket(0, GLOBAL_PACKET_CREDIT));
  }

  _receiveConnect(streamId, payload) {
    if (this.phase !== "ready") {
      this._protocolFailure("connect-before-ready");
      return;
    }
    if (streamId === 0 || this.streams.has(streamId)) {
      this._sendPacket(wispClosePacket(
          streamId, WISP_CLOSE_REASONS.INVALID_STREAM));
      return;
    }
    if (this.streams.size >= MAX_STREAMS_PER_RELAY || payload.length < 4 ||
        payload[0] !== 0x01) {  // TCP only.
      if (payload.length > 0 && payload[0] === 0x02) {
        this.context.stats.udpPackets += 1;
      }
      this.context.stats.rejectedDestinations += 1;
      this._sendPacket(wispClosePacket(streamId, WISP_CLOSE_REASONS.BLOCKED));
      this.context.transcript.add("connect-rejected", {streamId});
      return;
    }
    const port = payload.readUInt16LE(1);
    const hostname = decodeHostname(payload.subarray(3));
    const route = hostname ? this.context.destinationRoutes.get(
        destinationRouteKey(hostname, port)) : null;
    if (!route) {
      this.context.stats.rejectedDestinations += 1;
      this._sendPacket(wispClosePacket(streamId, WISP_CLOSE_REASONS.BLOCKED));
      if (hostname === TEST_HOSTNAME && port === LOCAL_GATEWAY_BLOCKED_PORT) {
        incrementBoundedCounter(
            this.context, "localGatewayBlockedPortAttempts");
        // Keep the controlled status record destination-free. The test's
        // fixed 444 attempt is proven by this event plus the absence of a
        // requested-destination record, rather than by serializing a client
        // supplied hostname or URL.
        this.context.transcript.add("local-gateway-444-blocked");
      } else {
        this.context.transcript.add("connect-rejected", {streamId, port});
      }
      return;
    }
    // The mixed-content target deliberately shares this exact cleartext
    // a.test listener with the positive plaintext control. Once that control
    // has completed, no later WISP CONNECT may reach its port. Count the
    // attempt before net.connect() so a failed TCP open cannot hide it.
    if (this.context.plaintextHttpControlPhase === "post-control" &&
        port === this.context.plaintextHttpControlPort) {
      incrementBoundedCounter(
          this.context, "mixedContentTargetPostControlWispConnects");
      this.context.transcript.add(
          "mixed-content-target-post-control-wisp-connect", {streamId, port});
    }

    const socket = net.connect({
      host: route.connectHost,
      port: route.connectPort,
      allowHalfOpen: false,
    });
    socket.setNoDelay(true);
    socket.setTimeout(DESTINATION_IDLE_TIMEOUT_MS);
    const stream = {
      id: streamId,
      port,
      routeKind: route.kind,
      socket,
      state: "connecting",
      closeSent: false,
      targetOutput: [],
      targetOutputBytes: 0,
      inboundBlocked: false,
      multiplexTargetKey: null,
      blockedBytes: 0,
      blockedFrames: 0,
      targetClosed: false,
    };
    this.streams.set(streamId, stream);
    appendRequestedDestination(this.context, hostname, port);
    this.context.transcript.add("connect-requested", {
      streamId,
      destination: `${TEST_HOSTNAME}:${port}`,
    });

    socket.on("connect", () => {
      if (this.closed || this.streams.get(streamId) !== stream) {
        socket.destroy();
        return;
      }
      stream.state = "open";
      if (stream.routeKind === "local-gateway-443") {
        incrementBoundedCounter(
            this.context, "localGateway443StreamsOpened");
      }
      this.context.transcript.add("connect-open", {
        streamId,
        destination: `${TEST_HOSTNAME}:${port}`,
      });
      // Register before granting the client stream credit. Chromium cannot
      // deliver TLS or HTTP bytes to this target before the WISP CONTINUE, so
      // the held multiplex handlers can correlate the target-side peer port
      // without a race or an observable stream identifier.
      registerMultiplexTargetStream(this.context, this, stream);
      this._sendPacket(wispContinuePacket(streamId, STREAM_PACKET_CREDIT));
    });
    socket.on("data", (bytes) => this._receiveTargetData(stream, bytes));
    socket.on("drain", () => this._destinationDrain(stream));
    socket.on("timeout", () => this._finishFromTarget(
        stream, WISP_CLOSE_REASONS.STREAM_TIMED_OUT, "target-timeout"));
    socket.on("end", () => this._finishFromTarget(
        stream, WISP_CLOSE_REASONS.VOLUNTARY, "target-eof"));
    socket.on("error", () => {
      this.context.stats.relayErrors += 1;
      this._finishFromTarget(
          stream, stream.state === "connecting" ? WISP_CLOSE_REASONS.REFUSED :
            WISP_CLOSE_REASONS.NETWORK_ERROR, "target-error");
    });
    socket.on("close", () => {
      if (!stream.targetClosed) {
        this._finishFromTarget(
            stream, WISP_CLOSE_REASONS.NETWORK_ERROR, "target-close");
      }
    });
  }

  _receiveData(streamId, payload) {
    if (this.phase !== "ready" || streamId === 0) {
      this._protocolFailure("data-before-ready");
      return;
    }
    const stream = this.streams.get(streamId);
    if (!stream || stream.state !== "open") {
      this._sendPacket(wispClosePacket(
          streamId, WISP_CLOSE_REASONS.INVALID_STREAM));
      return;
    }
    if (payload.length > MAX_WISP_DATA_PAYLOAD_BYTES ||
        this.inboundFrames + 1 > MAX_GLOBAL_INGRESS_FRAMES ||
        stream.blockedBytes + payload.length > MAX_STREAM_INGRESS_BYTES ||
        this.inboundBytes + payload.length > MAX_GLOBAL_INGRESS_BYTES) {
      this._finishFromTarget(
          stream, WISP_CLOSE_REASONS.THROTTLED, "ingress-limit");
      return;
    }

    // Copy before handing data to Node's asynchronous socket writer. This
    // makes the relay own its bounded queued bytes independently of the raw
    // WebSocket receive buffer.
    const data = Buffer.from(payload);
    this.inboundFrames += 1;
    this.inboundBytes += data.length;
    stream.blockedFrames += 1;
    stream.blockedBytes += data.length;
    const writable = stream.socket.write(data);
    if (writable) {
      this._consumeIngress(stream, data.length, 1);
      this._sendPacket(wispContinuePacket(stream.id, STREAM_PACKET_CREDIT));
      return;
    }
    stream.inboundBlocked = true;
    this.peer.pauseInput();
  }

  _receiveClose(streamId, payload) {
    if (this.phase !== "ready" || payload.length !== 1) {
      this._protocolFailure("invalid-close");
      return;
    }
    if (streamId === 0) {
      this._protocolFailure("client-closed-control");
      return;
    }
    const stream = this.streams.get(streamId);
    if (stream) {
      this.context.transcript.add("stream-client-close", {streamId});
      this._removeStream(stream, {destroy: true});
    }
  }

  _destinationDrain(stream) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        !stream.inboundBlocked) {
      return;
    }
    const bytes = stream.blockedBytes;
    const frames = stream.blockedFrames;
    stream.inboundBlocked = false;
    this._consumeIngress(stream, bytes, frames);
    this._sendPacket(wispContinuePacket(stream.id, STREAM_PACKET_CREDIT));
    if (![...this.streams.values()].some((candidate) =>
      candidate.inboundBlocked)) {
      this.peer.resumeInput();
    }
  }

  _consumeIngress(stream, bytes, frames) {
    stream.blockedBytes = Math.max(0, stream.blockedBytes - bytes);
    stream.blockedFrames = Math.max(0, stream.blockedFrames - frames);
    this.inboundBytes = Math.max(0, this.inboundBytes - bytes);
    this.inboundFrames = Math.max(0, this.inboundFrames - frames);
  }

  _receiveTargetData(stream, bytes) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        stream.state !== "open") {
      return;
    }
    const data = Buffer.from(bytes);
    for (let offset = 0; offset < data.length;
         offset += MAX_WISP_DATA_PAYLOAD_BYTES) {
      const chunk = data.subarray(
          offset, Math.min(offset + MAX_WISP_DATA_PAYLOAD_BYTES, data.length));
      if (stream.targetOutputBytes + chunk.length > MAX_STREAM_EGRESS_BYTES ||
          this.egressBytes + chunk.length > MAX_GLOBAL_EGRESS_BYTES) {
        this._finishFromTarget(
            stream, WISP_CLOSE_REASONS.THROTTLED, "egress-limit");
        return;
      }
      stream.targetOutput.push(Buffer.from(chunk));
      stream.targetOutputBytes += chunk.length;
      this.egressBytes += chunk.length;
    }
    this._flushTargetOutput();
  }

  _flushTargetOutput() {
    if (this.closed || this.peer.backpressured) {
      for (const stream of this.streams.values()) {
        if (stream.targetOutputBytes > 0) {
          stream.socket.pause();
        }
      }
      return;
    }
    for (const stream of this.streams.values()) {
      while (stream.targetOutput.length > 0 && !this.peer.backpressured) {
        const chunk = stream.targetOutput.shift();
        stream.targetOutputBytes -= chunk.length;
        this.egressBytes -= chunk.length;
        const sent = this._sendPacket(wispPacket(
            WISP_PACKET_TYPES.DATA, stream.id, chunk));
        if (!sent.accepted || sent.blocked) {
          stream.socket.pause();
          break;
        }
      }
      if (!this.peer.backpressured && stream.targetOutput.length === 0 &&
          !stream.targetClosed) {
        stream.socket.resume();
      }
    }
  }

  _finishFromTarget(stream, reason, event) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        stream.targetClosed) {
      return;
    }
    stream.targetClosed = true;
    this.context.transcript.add(event, {streamId: stream.id});
    if (!stream.closeSent) {
      stream.closeSent = true;
      this._sendPacket(wispClosePacket(stream.id, reason));
    }
    this._removeStream(stream, {destroy: true});
  }

  _removeStream(stream, options) {
    if (this.streams.get(stream.id) !== stream) {
      return;
    }
    this.streams.delete(stream.id);
    unregisterMultiplexTargetStream(this.context, stream);
    if (stream.blockedBytes > 0 || stream.blockedFrames > 0) {
      this._consumeIngress(stream, stream.blockedBytes, stream.blockedFrames);
    }
    this.egressBytes = Math.max(0, this.egressBytes - stream.targetOutputBytes);
    stream.targetOutput = [];
    stream.targetOutputBytes = 0;
    stream.targetClosed = true;
    if (options.destroy && !stream.socket.destroyed) {
      stream.socket.destroy();
    }
    if (![...this.streams.values()].some((candidate) =>
      candidate.inboundBlocked)) {
      this.peer.resumeInput();
    }
  }

  _sendPacket(packet) {
    const result = this.peer.sendBinary(packet);
    if (!result.accepted) {
      this.close();
    }
    return result;
  }

  _protocolFailure(event) {
    if (this.closed) {
      return;
    }
    this.context.stats.relayErrors += 1;
    this.context.transcript.add("wisp-protocol-error", {event});
    this._sendPacket(wispClosePacket(
        0, WISP_CLOSE_REASONS.INCOMPATIBLE_EXTENSIONS));
    this.peer.close(1002, "wisp-protocol-error");
    this.close();
  }
}

function multiplexTargetKey(destinationPort, sourcePort) {
  return `${destinationPort}:${sourcePort}`;
}

function isMultiplexTargetPort(context, port) {
  // The fixed logical HTTPS route uses the same source-port correlation as
  // the multiplex lane. The target listener remains the H2 fixture, but the
  // WISP stream's destination port must stay 443 so the handler can prove the
  // relay performed its explicit mapping.
  return port === context.h2Port || port === context.h1Port ||
      port === LOCAL_GATEWAY_HTTPS_PORT;
}

function registerMultiplexTargetStream(context, relay, stream) {
  if (!isMultiplexTargetPort(context, stream.port) ||
      !Number.isSafeInteger(stream.socket.localPort)) {
    return;
  }
  const key = multiplexTargetKey(stream.port, stream.socket.localPort);
  const existing = context.wispTargetStreamsBySourcePort.get(key);
  // A live outgoing TCP connection has a unique local port. Preserve the
  // original mapping on an impossible collision so a target request becomes a
  // deterministic correlation failure instead of being attributed to the
  // wrong WISP stream.
  if (existing && existing.stream !== stream) {
    return;
  }
  context.wispTargetStreamsBySourcePort.set(key, {relay, stream});
  stream.multiplexTargetKey = key;
}

function unregisterMultiplexTargetStream(context, stream) {
  const key = stream.multiplexTargetKey;
  if (!key) {
    return;
  }
  const record = context.wispTargetStreamsBySourcePort.get(key);
  if (record?.stream === stream) {
    context.wispTargetStreamsBySourcePort.delete(key);
  }
  stream.multiplexTargetKey = null;
}

function correlatedMultiplexTargetStream(context, destinationPort, sourcePort) {
  if (!Number.isSafeInteger(sourcePort)) {
    return null;
  }
  const record = context.wispTargetStreamsBySourcePort.get(
      multiplexTargetKey(destinationPort, sourcePort));
  if (!record || record.stream.port !== destinationPort ||
      record.stream.state !== "open" || record.relay.closed ||
      record.relay.streams.get(record.stream.id) !== record.stream) {
    return null;
  }
  return record;
}

function writeJson(response, status, body) {
  const json = JSON.stringify(body);
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Length": Buffer.byteLength(json),
    "Content-Type": "application/json; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(json);
}

function h2Headers(extra = {}) {
  return {
    "cache-control": "no-store",
    "content-security-policy": "default-src 'self'; base-uri 'none'; object-src 'none'",
    "x-content-type-options": "nosniff",
    // Chromium's Wasm transport deliberately disables QUIC. This makes the
    // test origin advertise H3 while continuing to prove the TCP/H2 path.
    "alt-svc": 'h3=":443"; ma=60',
    ...extra,
  };
}

function writeMultiplexH2Response(stream, accepted) {
  if (stream.destroyed || stream.closed) {
    return false;
  }
  const body = Buffer.from(accepted ? MULTIPLEX_H2_BODY :
      "M5_WISP_MULTIPLEX_REJECTED");
  try {
    stream.respond(h2Headers({
      ":status": accepted ? 200 : 409,
      "content-length": String(body.length),
      "content-type": "text/plain; charset=utf-8",
      "x-m5-wisp-multiplex": accepted ? "complete" : "rejected",
    }));
    stream.end(body);
    return true;
  } catch (_) {
    return false;
  }
}

function writeMultiplexH1Response(response, pageOrigin, accepted) {
  if (response.destroyed || response.writableEnded) {
    return false;
  }
  const body = accepted ? MULTIPLEX_H1_BODY : "M5_WISP_MULTIPLEX_REJECTED";
  try {
    response.writeHead(accepted ? 200 : 409, {
      "Access-Control-Allow-Origin": pageOrigin,
      "Cache-Control": "no-store",
      // Do not let the later CORS fetch or inner WebSocket reuse this held
      // connection. They remain independent fixed M5 transport checks.
      "Connection": "close",
      "Content-Length": String(Buffer.byteLength(body)),
      "Content-Type": "text/plain; charset=utf-8",
      "Vary": "Origin",
      "X-Content-Type-Options": "nosniff",
      "X-M5-Wisp-Multiplex": accepted ? "complete" : "rejected",
    });
    response.end(body);
    return true;
  } catch (_) {
    return false;
  }
}

function clearMultiplexPending(context, pending) {
  if (context.multiplexPending.get(pending.lane) !== pending) {
    return false;
  }
  context.multiplexPending.delete(pending.lane);
  clearTimeout(pending.timeout);
  pending.timeout = null;
  return true;
}

function discardMultiplexPending(context) {
  for (const pending of [...context.multiplexPending.values()]) {
    clearMultiplexPending(context, pending);
    pending.released = true;
  }
}

function failMultiplexBarrier(context, phase, event, counterName) {
  if (context.multiplexPhase === "complete" ||
      context.multiplexPhase === "barrier-timeout" ||
      context.multiplexPhase === "correlation-failed" ||
      context.multiplexPhase === "unexpected-close") {
    return;
  }
  context.multiplexPhase = phase;
  incrementBoundedCounter(context, counterName);
  context.transcript.add(event);
  for (const pending of [...context.multiplexPending.values()]) {
    clearMultiplexPending(context, pending);
    pending.released = true;
    pending.respond(false);
  }
}

function rejectMultiplexRequest(context, lane, respond) {
  if (context.multiplexPhase !== "complete") {
    failMultiplexBarrier(
        context, "correlation-failed", `${lane}-multiplex-correlation-failed`,
        "multiplexCorrelationFailures");
  }
  respond(false);
}

function releaseMultiplexBarrier(context) {
  if (context.multiplexPhase !== "awaiting-streams" ||
      context.multiplexPending.size !== 2) {
    return;
  }
  const h2Pending = context.multiplexPending.get("h2");
  const h1Pending = context.multiplexPending.get("h1");
  if (!h2Pending || !h1Pending) {
    return;
  }
  const h2Record = h2Pending.record;
  const h1Record = h1Pending.record;
  const bothStreamsOpen = [h2Record, h1Record].every((record) =>
    record.relay.streams.get(record.stream.id) === record.stream &&
    record.stream.state === "open");
  const sameCarrier = h2Record.relay === h1Record.relay &&
      h2Record.relay.carrierId === h1Record.relay.carrierId;
  const distinctStreams = h2Record.stream.id !== h1Record.stream.id;
  const distinctTargets = h2Record.stream.port === context.h2Port &&
      h1Record.stream.port === context.h1Port &&
      context.h2Port !== context.h1Port;
  // The first WISP carrier is deliberately still alive here. The only second
  // carrier in this fixture is created later by the reconnect lane.
  if (!bothStreamsOpen || !sameCarrier || !distinctStreams ||
      !distinctTargets || context.relays.size !== 1) {
    failMultiplexBarrier(
        context, "correlation-failed", "wisp-multiplex-correlation-failed",
        "multiplexCorrelationFailures");
    return;
  }

  context.stats.multiplexDistinctWispStreamCount = 2;
  context.stats.multiplexSharedCarrier = true;
  context.stats.multiplexBothStreamsOpen = true;
  context.multiplexPhase = "releasing";
  incrementBoundedCounter(context, "multiplexBarrierReleases");
  // This intentionally reveals only fixed assertions. Stream IDs, source
  // ports, and carrier identity remain private relay bookkeeping.
  context.transcript.add("wisp-multiplex-two-streams-live");

  const pendings = [h2Pending, h1Pending];
  for (const pending of pendings) {
    clearMultiplexPending(context, pending);
    pending.released = true;
  }
  let responses = 0;
  for (const pending of pendings) {
    if (!pending.respond(true)) {
      context.multiplexPhase = "unexpected-close";
      incrementBoundedCounter(context, "multiplexUnexpectedCloses");
      context.transcript.add(`${pending.lane}-multiplex-unexpected-close`);
      return;
    }
    responses += 1;
    incrementBoundedCounter(context, "multiplexResponses");
    context.transcript.add(`${pending.lane}-multiplex-complete`);
  }
  if (responses === 2) {
    context.multiplexPhase = "complete";
  }
}

function holdMultiplexRequest(context, lane, record, respond, observeClose) {
  if (context.multiplexPhase !== "pre-multiplex" &&
      context.multiplexPhase !== "awaiting-streams") {
    rejectMultiplexRequest(context, lane, respond);
    return;
  }
  if (context.multiplexPending.has(lane)) {
    rejectMultiplexRequest(context, lane, respond);
    return;
  }
  const pending = {lane, record, respond, released: false, timeout: null};
  context.multiplexPending.set(lane, pending);
  context.multiplexPhase = "awaiting-streams";
  incrementBoundedCounter(context, lane === "h2" ?
      "multiplexH2Requests" : "multiplexH1Requests");
  context.transcript.add(`${lane}-multiplex-pending`);
  pending.timeout = setTimeout(() => {
    if (context.multiplexPending.get(lane) !== pending) {
      return;
    }
    failMultiplexBarrier(
        context, "barrier-timeout", "wisp-multiplex-barrier-timeout",
        "multiplexBarrierTimeouts");
  }, MULTIPLEX_BARRIER_TIMEOUT_MS);
  pending.timeout.unref?.();

  let closeObserved = false;
  observeClose(() => {
    if (closeObserved || pending.released ||
        context.multiplexPending.get(lane) !== pending) {
      return;
    }
    closeObserved = true;
    failMultiplexBarrier(
        context, "unexpected-close", `${lane}-multiplex-unexpected-close`,
        "multiplexUnexpectedCloses");
  });
  releaseMultiplexBarrier(context);
}

function handleMultiplexH2Request(stream, context) {
  const record = correlatedMultiplexTargetStream(
      context, context.h2Port, stream.session?.socket?.remotePort);
  const respond = (accepted) => writeMultiplexH2Response(stream, accepted);
  if (!record) {
    rejectMultiplexRequest(context, "h2", respond);
    return;
  }
  holdMultiplexRequest(context, "h2", record, respond, (callback) => {
    stream.once("aborted", callback);
    stream.once("close", callback);
    stream.once("error", callback);
  });
}

function handleLocalGatewayProbe(stream, context) {
  const pageOrigin = `https://${TEST_HOSTNAME}:${context.h2Port}`;
  const record = correlatedMultiplexTargetStream(
      context, LOCAL_GATEWAY_HTTPS_PORT, stream.session?.socket?.remotePort);
  const accepted = !!record &&
      record.stream.routeKind === "local-gateway-443";
  if (!accepted) {
    const body = Buffer.from("M5_LOCAL_GATEWAY_ROUTE_REJECTED");
    stream.respond(h2Headers({
      ":status": 409,
      "access-control-allow-origin": pageOrigin,
      "content-length": String(body.length),
      "content-type": "text/plain; charset=utf-8",
      "vary": "Origin",
    }));
    stream.end(body);
    context.transcript.add("local-gateway-443-route-rejected");
    return;
  }
  const body = Buffer.from(LOCAL_GATEWAY_PROBE_BODY);
  incrementBoundedCounter(context, "localGateway443Requests");
  stream.respond(h2Headers({
    ":status": 200,
    "access-control-allow-origin": pageOrigin,
    "access-control-expose-headers":
      "x-m5-http-version, x-m5-local-gateway",
    "content-length": String(body.length),
    "content-type": "text/plain; charset=utf-8",
    "vary": "Origin",
    "x-m5-http-version": "h2",
    "x-m5-local-gateway": "mapped-443",
  }));
  stream.end(body);
  context.transcript.add("local-gateway-443-request");
}

function handleMultiplexH1Request(request, response, context) {
  const pageOrigin = `https://${TEST_HOSTNAME}:${context.h2Port}`;
  const respond = (accepted) =>
    writeMultiplexH1Response(response, pageOrigin, accepted);
  if (request.headers.origin !== pageOrigin) {
    rejectMultiplexRequest(context, "h1", respond);
    return;
  }
  const record = correlatedMultiplexTargetStream(
      context, context.h1Port, request.socket.remotePort);
  if (!record) {
    rejectMultiplexRequest(context, "h1", respond);
    return;
  }
  holdMultiplexRequest(context, "h1", record, respond, (callback) => {
    request.once("aborted", callback);
    request.once("close", callback);
    request.once("error", callback);
  });
}

function respondToCancelStreamProof(stream, context, accepted) {
  if (stream.destroyed || stream.closed) {
    return;
  }
  const body = Buffer.from(accepted
      ? CANCEL_STREAM_PROOF_BODY
      : "M5_CANCEL_STREAM_PROOF_REJECTED");
  try {
    stream.respond(h2Headers({
      ":status": accepted ? 200 : 409,
      "content-length": String(body.length),
      "content-type": "text/plain; charset=utf-8",
      "x-m5-cancel-stream-proof": accepted ? "cancel-observed" : "rejected",
    }));
    stream.end(body);
  } catch (_) {
    // The fixture only owns its response while the peer keeps the proof
    // stream alive. A cancelled proof cannot be made successful later.
    return;
  }
  if (accepted) {
    incrementBoundedCounter(context, "cancelStreamProofs");
    context.transcript.add("h2-cancel-stream-proof");
  } else {
    context.transcript.add("h2-cancel-stream-proof-rejected");
  }
}

function isCancelStreamProofSession(context, stream) {
  return context.cancelStreamSession !== null &&
      stream.session === context.cancelStreamSession;
}

function rejectCancelStreamProofSessionMismatch(stream, context) {
  incrementBoundedCounter(context, "cancelStreamProofSessionMismatches");
  context.transcript.add("h2-cancel-stream-proof-session-mismatch");
  respondToCancelStreamProof(stream, context, false);
}

function resolvePendingCancelStreamProofs(context, accepted) {
  for (const pending of [...context.cancelStreamPendingProofs]) {
    context.cancelStreamPendingProofs.delete(pending);
    clearTimeout(pending.timeout);
    if (accepted && !isCancelStreamProofSession(context, pending.stream)) {
      rejectCancelStreamProofSessionMismatch(pending.stream, context);
      continue;
    }
    respondToCancelStreamProof(pending.stream, context, accepted);
  }
}

function holdCancelStreamProof(context, stream) {
  const pending = {stream, timeout: null};
  context.cancelStreamPendingProofs.add(pending);
  pending.timeout = setTimeout(() => {
    if (!context.cancelStreamPendingProofs.delete(pending)) {
      return;
    }
    incrementBoundedCounter(context, "cancelStreamProofTimeouts");
    context.transcript.add("h2-cancel-stream-proof-timeout");
    respondToCancelStreamProof(stream, context, false);
  }, CANCEL_STREAM_PROOF_TIMEOUT_MS);
  pending.timeout.unref?.();
  stream.once("close", () => {
    if (context.cancelStreamPendingProofs.delete(pending)) {
      clearTimeout(pending.timeout);
    }
  });
}

function isSlowStreamSession(context, stream) {
  return context.slowStreamSession !== null &&
      stream.session === context.slowStreamSession;
}

function respondToSlowStreamControl(stream, status, body, state) {
  if (stream.destroyed || stream.closed) {
    return false;
  }
  const responseBody = Buffer.from(body);
  try {
    stream.respond(h2Headers({
      ":status": status,
      "content-length": String(responseBody.length),
      "content-type": "text/plain; charset=utf-8",
      "x-m5-slow-stream": state,
    }));
    stream.end(responseBody);
    return true;
  } catch (_) {
    return false;
  }
}

function respondToLargeDownloadControl(stream, status, body, state) {
  if (stream.destroyed || stream.closed) {
    return false;
  }
  const responseBody = Buffer.from(body);
  try {
    stream.respond(h2Headers({
      ":status": status,
      "content-length": String(responseBody.length),
      "content-type": "text/plain; charset=utf-8",
      "x-m5-large-download": state,
    }));
    stream.end(responseBody);
    return true;
  } catch (_) {
    return false;
  }
}

function clearSlowStreamStageAckTimeout(context) {
  if (context.slowStreamStageAckTimeout !== null) {
    clearTimeout(context.slowStreamStageAckTimeout);
    context.slowStreamStageAckTimeout = null;
  }
}

function clearSlowStreamStageTimer(context) {
  if (context.slowStreamStageTimer !== null) {
    clearTimeout(context.slowStreamStageTimer);
    context.slowStreamStageTimer = null;
  }
}

function clearReconnectTimers(context) {
  if (context.reconnectDisconnectTimer !== null) {
    clearTimeout(context.reconnectDisconnectTimer);
    context.reconnectDisconnectTimer = null;
  }
}

function clearPendingReconnectRecovery(context) {
  const pending = context.reconnectPendingRecovery;
  if (pending === null) {
    return null;
  }
  context.reconnectPendingRecovery = null;
  clearTimeout(pending.timeout);
  return pending;
}

function armSlowStreamStageAckTimeout(context, expectedPhases) {
  clearSlowStreamStageAckTimeout(context);
  context.slowStreamStageAckTimeout = setTimeout(() => {
    context.slowStreamStageAckTimeout = null;
    if (!expectedPhases.includes(context.slowStreamPhase)) {
      return;
    }
    context.slowStreamPhase = "stage-ack-timeout";
    incrementBoundedCounter(context, "slowStreamStageAckTimeouts");
    context.transcript.add("h2-slow-stream-stage-ack-timeout");
    if (context.slowStreamResponse && !context.slowStreamResponse.destroyed &&
        !context.slowStreamResponse.closed) {
      context.slowStreamResponse.close(http2.constants.NGHTTP2_CANCEL);
    }
  }, SLOW_STREAM_STAGE_ACK_TIMEOUT_MS);
  context.slowStreamStageAckTimeout.unref?.();
}

function writeSlowStreamStage(context, stageIndex) {
  const stream = context.slowStreamResponse;
  if (!stream || stream.destroyed || stream.closed ||
      stageIndex < 0 || stageIndex >= SLOW_STREAM_STAGES.length) {
    return false;
  }
  const body = Buffer.from(SLOW_STREAM_STAGES[stageIndex]);
  try {
    if (stageIndex === 0) {
      stream.respond(h2Headers({
        ":status": 200,
        "content-type": "text/plain; charset=utf-8",
        "x-m5-slow-stream": "streaming",
      }));
    }
    stream.write(body);
  } catch (_) {
    return false;
  }

  if (stageIndex === 0) {
    context.slowStreamPhase = "first-stage";
    incrementBoundedCounter(context, "slowStreamFirstStages");
    context.transcript.add("h2-slow-stream-first-stage");
    armSlowStreamStageAckTimeout(context, ["first-stage"]);
    return true;
  }
  if (stageIndex === 1) {
    context.slowStreamPhase = "second-stage";
    incrementBoundedCounter(context, "slowStreamSecondStages");
    context.transcript.add("h2-slow-stream-second-stage");
    armSlowStreamStageAckTimeout(context, [
      "second-stage",
      "second-stage-consumer-paused",
      "second-stage-consumer-resumed",
    ]);
    return true;
  }

  clearSlowStreamStageAckTimeout(context);
  context.slowStreamPhase = "complete";
  incrementBoundedCounter(context, "slowStreamThirdStages");
  context.transcript.add("h2-slow-stream-third-stage");
  try {
    stream.end();
  } catch (_) {
    return false;
  }
  incrementBoundedCounter(context, "slowStreamCompletedStreams");
  context.transcript.add("h2-slow-stream-complete");
  return true;
}

function scheduleSlowStreamStage(context, expectedPhase, stageIndex) {
  clearSlowStreamStageTimer(context);
  incrementBoundedCounter(context, "slowStreamStageDelaySchedules");
  context.slowStreamStageTimer = setTimeout(() => {
    context.slowStreamStageTimer = null;
    if (context.slowStreamPhase !== expectedPhase) {
      return;
    }
    if (!writeSlowStreamStage(context, stageIndex)) {
      context.slowStreamPhase = "unexpected-close";
      incrementBoundedCounter(context, "slowStreamUnexpectedCloses");
      context.transcript.add("h2-slow-stream-unexpected-close");
    }
  }, context.slowStreamStageDelayMs);
  context.slowStreamStageTimer.unref?.();
}

function rejectSlowStreamSessionMismatch(stream, context, event) {
  incrementBoundedCounter(context, "slowStreamSessionMismatches");
  context.transcript.add(event);
  respondToSlowStreamControl(
      stream, 409, "M5_SLOW_STREAM_REJECTED", "session-mismatch");
}

function writeSlowStreamConsumerBurst(context) {
  const stream = context.slowStreamResponse;
  if (!stream || stream.destroyed || stream.closed) {
    return false;
  }
  const body = Buffer.alloc(
      SLOW_STREAM_CONSUMER_BURST_BYTES, SLOW_STREAM_CONSUMER_BURST_BYTE);
  try {
    const writable = stream.write(body);
    context.stats.slowStreamConsumerBurstBytes = body.length;
    incrementBoundedCounter(context, "slowStreamConsumerBurstWrites");
    context.transcript.add("h2-slow-stream-consumer-burst", {
      backpressured: !writable,
      bytes: body.length,
    });
    return true;
  } catch (_) {
    return false;
  }
}

function handleSlowStreamConsumerPauseReady(stream, context) {
  if (!isSlowStreamSession(context, stream)) {
    rejectSlowStreamSessionMismatch(
        stream, context, "h2-slow-stream-consumer-pause-ready-session-mismatch");
    return;
  }
  if (context.slowStreamPhase !== "second-stage") {
    context.transcript.add("h2-slow-stream-consumer-pause-ready-rejected");
    respondToSlowStreamControl(stream, 409, "M5_SLOW_STREAM_REJECTED", "rejected");
    return;
  }

  context.slowStreamPhase = "second-stage-consumer-paused";
  incrementBoundedCounter(context, "slowStreamConsumerPauseReadyRequests");
  context.transcript.add("h2-slow-stream-consumer-pause-ready");
  if (!writeSlowStreamConsumerBurst(context) ||
      !respondToSlowStreamControl(
          stream, 200, SLOW_STREAM_CONSUMER_PAUSE_READY_BODY, "paused")) {
    context.slowStreamPhase = "unexpected-close";
    incrementBoundedCounter(context, "slowStreamUnexpectedCloses");
    context.transcript.add("h2-slow-stream-unexpected-close");
  }
}

function handleSlowStreamConsumerResume(stream, context) {
  if (!isSlowStreamSession(context, stream)) {
    rejectSlowStreamSessionMismatch(
        stream, context, "h2-slow-stream-consumer-resume-session-mismatch");
    return;
  }
  if (context.slowStreamPhase !== "second-stage-consumer-paused") {
    context.transcript.add("h2-slow-stream-consumer-resume-rejected");
    respondToSlowStreamControl(stream, 409, "M5_SLOW_STREAM_REJECTED", "rejected");
    return;
  }

  context.slowStreamPhase = "second-stage-consumer-resumed";
  incrementBoundedCounter(context, "slowStreamConsumerResumes");
  context.transcript.add("h2-slow-stream-consumer-resume");
  if (!respondToSlowStreamControl(
      stream, 200, SLOW_STREAM_CONSUMER_RESUME_BODY, "resumed")) {
    context.slowStreamPhase = "unexpected-close";
    incrementBoundedCounter(context, "slowStreamUnexpectedCloses");
    context.transcript.add("h2-slow-stream-unexpected-close");
  }
}

function handleSlowStreamStageAck(stream, context, stageIndex) {
  if (!isSlowStreamSession(context, stream)) {
    rejectSlowStreamSessionMismatch(
        stream, context, "h2-slow-stream-stage-ack-session-mismatch");
    return;
  }

  const expectedPhase = stageIndex === 0 ? "first-stage" :
    "second-stage-consumer-resumed";
  const acknowledgedPhase = stageIndex === 0 ?
    "first-stage-acknowledged" : "second-stage-acknowledged";
  const body = stageIndex === 0 ? SLOW_STREAM_FIRST_STAGE_ACK_BODY :
    SLOW_STREAM_SECOND_STAGE_ACK_BODY;
  if (context.slowStreamPhase !== expectedPhase) {
    context.transcript.add("h2-slow-stream-stage-ack-rejected");
    respondToSlowStreamControl(stream, 409, "M5_SLOW_STREAM_REJECTED", "rejected");
    return;
  }

  clearSlowStreamStageAckTimeout(context);
  context.slowStreamPhase = acknowledgedPhase;
  if (stageIndex === 0) {
    incrementBoundedCounter(context, "slowStreamFirstStageAcks");
    context.transcript.add("h2-slow-stream-first-stage-ack");
  } else {
    incrementBoundedCounter(context, "slowStreamSecondStageAcks");
    context.transcript.add("h2-slow-stream-second-stage-ack");
  }
  if (!respondToSlowStreamControl(stream, 200, body, "acknowledged")) {
    context.slowStreamPhase = "unexpected-close";
    incrementBoundedCounter(context, "slowStreamUnexpectedCloses");
    context.transcript.add("h2-slow-stream-unexpected-close");
    return;
  }
  scheduleSlowStreamStage(context, acknowledgedPhase, stageIndex + 1);
}

function handleSlowStreamProof(stream, context) {
  if (!isSlowStreamSession(context, stream)) {
    incrementBoundedCounter(context, "slowStreamSessionMismatches");
    context.transcript.add("h2-slow-stream-proof-session-mismatch");
    respondToSlowStreamControl(
        stream, 409, "M5_SLOW_STREAM_PROOF_REJECTED", "session-mismatch");
    return;
  }
  if (context.slowStreamPhase !== "complete") {
    context.transcript.add("h2-slow-stream-proof-rejected");
    respondToSlowStreamControl(
        stream, 409, "M5_SLOW_STREAM_PROOF_REJECTED", "rejected");
    return;
  }
  if (respondToSlowStreamControl(
      stream, 200, SLOW_STREAM_PROOF_BODY, "complete")) {
    incrementBoundedCounter(context, "slowStreamProofs");
    context.transcript.add("h2-slow-stream-proof");
  }
}

function largeDownloadChunk(offset) {
  const length = Math.min(
      LARGE_DOWNLOAD_CHUNK_BYTES, LARGE_DOWNLOAD_BYTES - offset);
  const body = Buffer.allocUnsafe(length);
  for (let index = 0; index < body.length; ++index) {
    // A byte position pattern catches truncation, duplication, reordering,
    // and fabricated all-zero bodies without serializing the large body into
    // a status response.
    body[index] = (offset + index) & 0xff;
  }
  return body;
}

function failLargeDownload(context, stream) {
  if (context.largeDownloadPhase === "complete" ||
      context.largeDownloadPhase === "unexpected-close") {
    return;
  }
  context.largeDownloadPhase = "unexpected-close";
  incrementBoundedCounter(context, "largeDownloadUnexpectedCloses");
  context.transcript.add("h2-large-download-unexpected-close");
  if (stream && !stream.destroyed && !stream.closed) {
    try {
      stream.close(http2.constants.NGHTTP2_CANCEL);
    } catch (_) {
      // The stream is already terminal, which is the failure being recorded.
    }
  }
}

function writeLargeDownload(context, stream) {
  if (context.largeDownloadPhase !== "pre-download") {
    context.transcript.add("h2-large-download-rejected");
    respondToLargeDownloadControl(
        stream, 409, "M5_LARGE_DOWNLOAD_REJECTED", "duplicate");
    return;
  }

  context.largeDownloadPhase = "streaming";
  incrementBoundedCounter(context, "largeDownloadRequests");
  context.transcript.add("h2-large-download-start");
  let bytesWritten = 0;
  let settled = false;
  const fail = () => {
    if (settled) {
      return;
    }
    settled = true;
    failLargeDownload(context, stream);
  };
  const finish = () => {
    if (settled) {
      return;
    }
    settled = true;
    context.largeDownloadPhase = "complete";
    incrementBoundedCounter(context, "largeDownloadCompletions");
    context.transcript.add("h2-large-download-complete");
    try {
      stream.end();
    } catch (_) {
      // Chromium's native DownloadManager validates the target file and byte
      // pattern before it releases the page workflow, so a failed end cannot
      // turn this into a passing attachment download.
      context.largeDownloadPhase = "unexpected-close";
      incrementBoundedCounter(context, "largeDownloadUnexpectedCloses");
      context.transcript.add("h2-large-download-unexpected-close");
    }
  };
  const pump = () => {
    if (settled || stream.destroyed || stream.closed) {
      fail();
      return;
    }
    while (bytesWritten < LARGE_DOWNLOAD_BYTES) {
      const body = largeDownloadChunk(bytesWritten);
      let writable = false;
      try {
        writable = stream.write(body);
      } catch (_) {
        fail();
        return;
      }
      bytesWritten += body.length;
      context.stats.largeDownloadBytes = bytesWritten;
      context.stats.largeDownloadChunks = Math.min(
          context.stats.largeDownloadChunks + 1, LARGE_DOWNLOAD_CHUNK_COUNT);
      if (!writable) {
        context.stats.largeDownloadBackpressureEvents = Math.min(
            context.stats.largeDownloadBackpressureEvents + 1,
            LARGE_DOWNLOAD_CHUNK_COUNT);
        stream.once("drain", pump);
        return;
      }
    }
    finish();
  };

  stream.once("aborted", fail);
  stream.once("close", fail);
  stream.once("error", fail);
  try {
    stream.respond(h2Headers({
      ":status": 200,
      "content-disposition": LARGE_DOWNLOAD_CONTENT_DISPOSITION,
      "content-length": String(LARGE_DOWNLOAD_BYTES),
      "content-type": "application/octet-stream",
      "x-m5-large-download": "streaming",
    }));
  } catch (_) {
    fail();
    return;
  }
  pump();
}

function isReconnectStreamSession(context, stream) {
  return context.reconnectStreamSession !== null &&
      stream.session === context.reconnectStreamSession;
}

function respondToReconnectControl(stream, status, body, state) {
  if (stream.destroyed || stream.closed) {
    return false;
  }
  const responseBody = Buffer.from(body);
  try {
    stream.respond(h2Headers({
      ":status": status,
      "content-length": String(responseBody.length),
      "content-type": "text/plain; charset=utf-8",
      "x-m5-wisp-reconnect": state,
    }));
    stream.end(responseBody);
    return true;
  } catch (_) {
    return false;
  }
}

function rejectReconnectControl(stream, context, event) {
  context.transcript.add(event);
  respondToReconnectControl(stream, 409, "M5_WISP_RECONNECT_REJECTED",
      "rejected");
}

function writeReconnectStream(context, stream) {
  incrementBoundedCounter(context, "reconnectStreamRequests");
  if (context.reconnectPhase !== "pre-reconnect") {
    incrementBoundedCounter(context, "reconnectUnexpectedRetries");
    rejectReconnectControl(stream, context, "h2-reconnect-stream-rejected");
    return;
  }

  context.reconnectPhase = "streaming";
  context.reconnectStreamSession = stream.session;
  context.transcript.add("h2-reconnect-stream-start");
  let closeObserved = false;
  const observeClose = () => {
    if (closeObserved) {
      return;
    }
    closeObserved = true;
    if (context.reconnectPhase === "disconnecting" ||
        context.reconnectPhase === "disconnected" ||
        context.reconnectPhase === "recovered") {
      context.transcript.add("h2-reconnect-stream-disconnected");
      return;
    }
    context.reconnectPhase = "unexpected-close";
    incrementBoundedCounter(context, "reconnectUnexpectedCloses");
    context.transcript.add("h2-reconnect-stream-unexpected-close");
  };
  stream.once("aborted", observeClose);
  stream.once("close", observeClose);
  stream.once("error", observeClose);
  try {
    stream.respond(h2Headers({
      ":status": 200,
      "content-length": String(RECONNECT_STREAM_CONTENT_LENGTH),
      "content-type": "text/plain; charset=utf-8",
      "x-m5-wisp-reconnect": "partial-stream",
    }));
    stream.write(RECONNECT_STREAM_FIRST_CHUNK);
  } catch (_) {
    observeClose();
    return;
  }
  incrementBoundedCounter(context, "reconnectFirstChunks");
  context.transcript.add("h2-reconnect-stream-first-chunk");
}

function scheduleReconnectDisconnect(context) {
  clearReconnectTimers(context);
  const disconnect = () => {
    context.reconnectDisconnectTimer = null;
    if (context.reconnectPhase !== "first-chunk-acknowledged") {
      return;
    }
    const relays = [...context.relays].filter((relay) => !relay.closed);
    if (relays.length !== 1) {
      context.reconnectPhase = "unexpected-close";
      incrementBoundedCounter(context, "reconnectUnexpectedCloses");
      context.transcript.add("h2-reconnect-relay-selection-failed");
      return;
    }

    context.reconnectPhase = "disconnecting";
    incrementBoundedCounter(context, "reconnectDisconnectRequests");
    context.transcript.add("h2-reconnect-disconnect-requested");
    const relay = relays[0];
    // The carrier itself is the failure under test. Do not send a WISP CLOSE:
    // the browser's RFC 6455 close event must map the pending stream to
    // ERR_INTERNET_DISCONNECTED. WebSocketPeer.close() writes a valid close
    // frame then ends the socket; avoid an immediate destroy, which could turn
    // this deliberate close into a browser error event instead.
    context.transcript.add("h2-reconnect-carrier-close");
    relay.peer.close(1000, "m5-carrier-close");
    if (context.reconnectPhase === "disconnecting") {
      context.reconnectPhase = "disconnected";
      context.transcript.add("h2-reconnect-wisp-disconnected");
      resolvePendingReconnectRecovery(context);
    }
  };
  // The exact same-session ACK response is sent immediately after this timer
  // is armed. The bounded delay leaves it a response window before ending the
  // old connection and keeps a stalled peer from retaining the fixture.
  context.reconnectDisconnectTimer = setTimeout(
      disconnect, RECONNECT_DISCONNECT_DELAY_MS);
  context.reconnectDisconnectTimer.unref?.();
}

function handleReconnectFirstChunkAck(stream, context) {
  if (context.reconnectPhase !== "streaming" ||
      !isReconnectStreamSession(context, stream)) {
    if (context.reconnectStreamSession !== null &&
        !isReconnectStreamSession(context, stream)) {
      incrementBoundedCounter(context, "reconnectSessionMismatches");
      rejectReconnectControl(
          stream, context, "h2-reconnect-first-chunk-ack-session-mismatch");
      return;
    }
    rejectReconnectControl(
        stream, context, "h2-reconnect-first-chunk-ack-rejected");
    return;
  }
  context.reconnectPhase = "first-chunk-acknowledged";
  incrementBoundedCounter(context, "reconnectFirstChunkAcks");
  context.transcript.add("h2-reconnect-first-chunk-ack");
  scheduleReconnectDisconnect(context);
  respondToReconnectControl(
      stream, 200, RECONNECT_FIRST_CHUNK_ACK_BODY, "first-chunk-acknowledged");
}

function completeReconnectRecovery(stream, context) {
  if (stream.destroyed || stream.closed) {
    return false;
  }
  context.reconnectPhase = "recovered";
  incrementBoundedCounter(context, "reconnectRecoveryRequests");
  context.transcript.add("h2-reconnect-recovery");
  return respondToReconnectControl(
      stream, 200, RECONNECT_RECOVERY_BODY, "recovered");
}

function holdReconnectRecovery(stream, context) {
  if (context.reconnectPendingRecovery !== null) {
    rejectReconnectControl(
        stream, context, "h2-reconnect-recovery-rejected");
    return;
  }
  const pending = {stream, timeout: null};
  context.reconnectPendingRecovery = pending;
  pending.timeout = setTimeout(() => {
    if (context.reconnectPendingRecovery !== pending) {
      return;
    }
    context.reconnectPendingRecovery = null;
    context.reconnectPhase = "unexpected-close";
    incrementBoundedCounter(context, "reconnectUnexpectedCloses");
    context.transcript.add("h2-reconnect-recovery-timeout");
    rejectReconnectControl(
        stream, context, "h2-reconnect-recovery-rejected");
  }, RECONNECT_RECOVERY_TIMEOUT_MS);
  pending.timeout.unref?.();
  stream.once("close", () => {
    if (context.reconnectPendingRecovery !== pending) {
      return;
    }
    context.reconnectPendingRecovery = null;
    clearTimeout(pending.timeout);
    context.reconnectPhase = "unexpected-close";
    incrementBoundedCounter(context, "reconnectUnexpectedCloses");
    context.transcript.add("h2-reconnect-recovery-unexpected-close");
  });
}

function resolvePendingReconnectRecovery(context) {
  const pending = clearPendingReconnectRecovery(context);
  if (pending === null) {
    return;
  }
  if (context.reconnectPhase !== "disconnected") {
    return;
  }
  if (!completeReconnectRecovery(pending.stream, context)) {
    context.reconnectPhase = "unexpected-close";
    incrementBoundedCounter(context, "reconnectUnexpectedCloses");
    context.transcript.add("h2-reconnect-recovery-unexpected-close");
  }
}

function handleReconnectRecovery(stream, context) {
  if (context.reconnectStreamSession !== null &&
      stream.session === context.reconnectStreamSession) {
    incrementBoundedCounter(context, "reconnectSessionMismatches");
    rejectReconnectControl(
        stream, context, "h2-reconnect-recovery-session-mismatch");
    return;
  }
  if (context.reconnectPhase === "disconnecting") {
    // The browser may receive the carrier close and create its fresh session
    // before this relay's old H2 stream reports its asynchronous teardown.
    // Hold that fresh request until the old relay is conclusively gone instead
    // of turning a valid reconnect race into a 409 response.
    holdReconnectRecovery(stream, context);
    return;
  }
  if (context.reconnectPhase !== "disconnected" ||
      context.reconnectStreamSession === null) {
    rejectReconnectControl(stream, context, "h2-reconnect-recovery-rejected");
    return;
  }
  completeReconnectRecovery(stream, context);
}

function h2Page(context) {
  const h1CorsUrl = `https://${TEST_HOSTNAME}:${context.h1Port}/m5/cors-resource`;
  const multiplexH1Url =
      `https://${TEST_HOSTNAME}:${context.h1Port}/m5/multiplex-h1`;
  const cspConnectSrcTargetUrl =
      `https://${TEST_HOSTNAME}:${context.cspConnectSrcTargetPort}/` +
      "m5/csp-connect-src-target";
  const mixedContentTargetUrl =
      "http://" + TEST_HOSTNAME + ":" + context.plaintextHttpControlPort +
      "/m5/mixed-content-target";
  const webSocketUrl = `wss://${TEST_HOSTNAME}:${context.h1Port}/m5/ws`;
  return `<!doctype html>
<meta charset="utf-8">
<title>Chromium Wasm M5 network fixture</title>
<style>body{font:16px sans-serif;margin:2rem}#m5-status{white-space:pre-wrap}</style>
<h1>Chromium Wasm M5 network fixture</h1>
<p id="m5-status">Loading Chromium-network checks…</p>
<script>
(() => {
  "use strict";
  const fixture = ${JSON.stringify(FIXTURE)};
  const cacheRevalidateURL =
      new URL("/m5/cache-revalidate", location.href).href;
  const cacheRevalidateETag = ${JSON.stringify(CACHE_REVALIDATE_ETAG)};
  const cspConnectSrcProofURL =
      new URL("/m5/csp-connect-src-proof", location.href).href;
  const cspConnectSrcTargetURL = ${JSON.stringify(cspConnectSrcTargetUrl)};
  const h2ResourceURL = new URL("/m5/h2-resource", location.href).href;
  const localGatewayProbeURL = ${JSON.stringify(
      `https://${TEST_HOSTNAME}:${LOCAL_GATEWAY_HTTPS_PORT}/m5/local-gateway-probe`)};
  const localGatewayDeniedURL = ${JSON.stringify(
      `https://${TEST_HOSTNAME}:${LOCAL_GATEWAY_BLOCKED_PORT}/m5/local-gateway-denied`)};
  const cancelStreamURL = new URL("/m5/cancel-stream", location.href).href;
  const cancelStreamProofURL =
      new URL("/m5/cancel-proof", location.href).href;
  const cancelStreamFirstChunk =
      ${JSON.stringify(CANCEL_STREAM_FIRST_CHUNK)};
  const slowStreamURL = new URL("/m5/slow-stream", location.href).href;
  const slowStreamFirstStageAckURL =
      new URL("/m5/slow-stream-first-stage-ack", location.href).href;
  const slowStreamSecondStageAckURL =
      new URL("/m5/slow-stream-second-stage-ack", location.href).href;
  const slowStreamConsumerPauseReadyURL =
      new URL("/m5/slow-stream-consumer-pause-ready", location.href).href;
  const slowStreamConsumerResumeURL =
      new URL("/m5/slow-stream-consumer-resume", location.href).href;
  const slowStreamProofURL =
      new URL("/m5/slow-stream-proof", location.href).href;
  const multiplexH2URL =
      new URL("/m5/multiplex-h2", location.href).href;
  const multiplexH1URL = ${JSON.stringify(multiplexH1Url)};
  const largeDownloadURL = new URL("/m5/large-download", location.href).href;
  const reconnectStreamURL =
      new URL("/m5/reconnect-stream", location.href).href;
  const reconnectFirstChunkAckURL =
      new URL("/m5/reconnect-first-chunk-ack", location.href).href;
  const reconnectRecoveryURL =
      new URL("/m5/reconnect-recovery", location.href).href;
  const slowStreamStages = ${JSON.stringify(SLOW_STREAM_STAGES)};
  const slowStreamConsumerBurstBytes = ${SLOW_STREAM_CONSUMER_BURST_BYTES};
  const slowStreamConsumerBurstByte = ${SLOW_STREAM_CONSUMER_BURST_BYTE};
  const slowStreamConsumerPauseMs = 150;
  const reconnectStreamFirstChunk =
      ${JSON.stringify(RECONNECT_STREAM_FIRST_CHUNK)};
  const mixedContentProofURL =
      new URL("/m5/mixed-content-proof", location.href).href;
  const mixedContentTargetURL = ${JSON.stringify(mixedContentTargetUrl)};
  const corsURL = ${JSON.stringify(h1CorsUrl)};
  const socketURL = ${JSON.stringify(webSocketUrl)};
  const navigationEntry = performance.getEntriesByType("navigation")[0];
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      (value) => value.toString(16).padStart(2, "0")).join("");
  const state = {
    timerTicks: 0,
    h2Fetch: false,
    h2Protocol: "",
    altSvcH3Advertised: false,
    localGatewayMappedRequestStarted: false,
    localGatewayMappedResponse: false,
    localGatewayBlockedRequestStarted: false,
    localGatewayBlocked: false,
    cacheStored: false,
    cacheRevalidated: false,
    cancelStreamStarted: false,
    cancelStreamReceivedFirstChunk: false,
    cancelStreamAborted: false,
    cancelStreamErrorName: "",
    cancelStreamProof: false,
    slowStreamStarted: false,
    slowStreamFirstStage: false,
    slowStreamSecondStage: false,
    slowStreamThirdStage: false,
    slowStreamComplete: false,
    slowStreamProof: false,
    slowStreamConsumerPauseStarted: false,
    slowStreamConsumerBurstRead: false,
    slowStreamConsumerResume: false,
    slowStreamElapsedMs: 0,
    slowStreamFirstToSecondStageDelayMs: 0,
    slowStreamSecondToThirdStageDelayMs: 0,
    slowStreamConsumerPauseElapsedMs: 0,
    slowStreamConsumerPauseTimerTicks: 0,
    slowStreamTimerTicksWhileWaiting: 0,
    multiplexRequestsStarted: false,
    multiplexH2Response: false,
    multiplexH1Response: false,
    multiplexComplete: false,
    largeDownloadNavigationRequested: false,
    largeDownloadNativeComplete: false,
    reconnectStreamStarted: false,
    reconnectFirstChunkReceived: false,
    reconnectFirstChunkAck: false,
    reconnectDisconnectRequested: false,
    reconnectStreamFailed: false,
    reconnectStreamErrorName: "",
    reconnectRecovered: false,
    reconnectRecoveryProtocol: "",
    activeMixedContentBlocked: false,
    activeMixedContentCspAllowed: false,
    activeMixedContentErrorName: "",
    cspConnectSrcBlocked: false,
    corsFetch: false,
    redirected: navigationEntry?.redirectCount === 1,
    webSocketEcho: false,
    complete: false,
    failure: null,
  };
  const status = document.querySelector("#m5-status");
  let resolveNativeDownloadComplete = null;
  const nativeDownloadComplete = new Promise((resolve) => {
    resolveNativeDownloadComplete = resolve;
  });

  // This page only requests the attachment navigation. Chromium's native M5
  // DownloadManager observer validates the response, target file, and byte
  // pattern before invoking this resolver. Keeping the resolver one-shot
  // makes the following reconnect causally depend on that browser-owned path.
  window.__chromiumWasmM5NativeDownloadComplete = () => {
    if (!state.largeDownloadNavigationRequested ||
        state.largeDownloadNativeComplete || !resolveNativeDownloadComplete) {
      return false;
    }
    state.largeDownloadNativeComplete = true;
    resolveNativeDownloadComplete();
    return true;
  };
  setInterval(() => { state.timerTicks += 1; }, 25);

  function nextHopProtocol(url) {
    const entries = performance.getEntriesByName(url, "resource");
    const entry = entries.length === 0 ? null : entries[entries.length - 1];
    return entry && entry.nextHopProtocol === "h2" ? "h2" : "";
  }

  function echoNonce() {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(socketURL);
      let settled = false;
      const finish = (callback, value) => {
        if (!settled) {
          settled = true;
          callback(value);
        }
      };
      socket.addEventListener("open", () => socket.send(nonce), {once: true});
      socket.addEventListener("message", (event) => {
        const matched = typeof event.data === "string" && event.data === nonce;
        socket.close(1000, "fixture-complete");
        finish(resolve, matched);
      }, {once: true});
      socket.addEventListener("error", () => finish(reject,
          new Error("M5 inner WebSocket failed")), {once: true});
      setTimeout(() => finish(reject,
          new Error("M5 inner WebSocket timed out")), 10000);
    });
  }

  function isCspConnectSrcTargetViolation(event) {
    // Fetch connect-src reports retain the complete blocked URL in Chromium.
    // Match it exactly so a report-only policy or another endpoint on this
    // loopback target cannot turn a transport error into a CSP pass.
    return event.disposition === "enforce" &&
        event.effectiveDirective === "connect-src" &&
        event.blockedURI === cspConnectSrcTargetURL;
  }

  function waitForCspConnectSrcTargetViolation() {
    return new Promise((resolve) => {
      let timeout = null;
      const listener = (event) => {
        if (!isCspConnectSrcTargetViolation(event)) {
          return;
        }
        clearTimeout(timeout);
        document.removeEventListener("securitypolicyviolation", listener);
        resolve(true);
      };
      document.addEventListener("securitypolicyviolation", listener);
      timeout = setTimeout(() => {
        document.removeEventListener("securitypolicyviolation", listener);
        resolve(false);
      }, 1000);
    });
  }

  async function verifyCspConnectSrcBlock() {
    const violation = waitForCspConnectSrcTargetViolation();
    let rejected = false;
    try {
      await fetch(cspConnectSrcTargetURL, {
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
      });
    } catch (_) {
      rejected = true;
    }
    return rejected && await violation;
  }

  async function verifyActiveMixedContentBlock() {
    let cspConnectSrcViolation = false;
    const listener = (event) => {
      if (event.disposition === "enforce" &&
          event.effectiveDirective === "connect-src" &&
          event.blockedURI === mixedContentTargetURL) {
        cspConnectSrcViolation = true;
      }
    };
    document.addEventListener("securitypolicyviolation", listener);
    let errorName = "";
    try {
      await fetch(mixedContentTargetURL, {
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
      });
    } catch (error) {
      errorName = typeof error?.name === "string" ? error.name : "";
    }
    // CSP violation delivery is asynchronous. Leave a bounded grace window
    // for an enforcing connect-src report before treating this as native
    // mixed-content rejection.
    await new Promise((resolve) => setTimeout(resolve, 50));
    document.removeEventListener("securitypolicyviolation", listener);
    return {
      cspAllowed: !cspConnectSrcViolation,
      errorName,
    };
  }

  async function verifyLocalGatewayRoute() {
    const result = {
      mappedRequestStarted: false,
      mappedResponse: false,
      blockedRequestStarted: false,
      blocked: false,
    };
    result.mappedRequestStarted = true;
    state.localGatewayMappedRequestStarted = true;
    try {
      const response = await fetch(localGatewayProbeURL, {
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
      });
      const body = await response.text();
      result.mappedResponse = response.ok && body ===
          ${JSON.stringify(LOCAL_GATEWAY_PROBE_BODY)} &&
          response.headers.get("x-m5-http-version") === "h2" &&
          response.headers.get("x-m5-local-gateway") === "mapped-443";
    } catch (_) {
      // Record the failed fixed mapping below. The result is deliberately a
      // boolean so the host never receives a target URL or transport detail.
    }
    state.localGatewayMappedResponse = result.mappedResponse;

    result.blockedRequestStarted = true;
    state.localGatewayBlockedRequestStarted = true;
    try {
      await fetch(localGatewayDeniedURL, {
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
      });
    } catch (error) {
      result.blocked = error?.name === "TypeError";
    }
    state.localGatewayBlocked = result.blocked;
    return result;
  }

  async function verifyCancelStream() {
    const controller = new AbortController();
    const response = await fetch(cancelStreamURL, {
      cache: "no-store",
      credentials: "omit",
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      return {started: false, receivedFirstChunk: false, errorName: ""};
    }
    const reader = response.body.getReader();
    let receivedChunk = "";
    // A fetch body is a stream, so a browser is free to split the exact
    // fixture payload across multiple reads. Accumulate it before aborting;
    // any extra bytes make the equality check fail instead of masking an
    // unexpected response body.
    while (receivedChunk.length < cancelStreamFirstChunk.length) {
      const next = await reader.read();
      if (next.done) {
        break;
      }
      receivedChunk += new TextDecoder().decode(next.value);
    }
    const receivedFirstChunk = receivedChunk === cancelStreamFirstChunk;
    if (!receivedFirstChunk) {
      try {
        await reader.cancel();
      } catch (_) {
        // Preserve the failed first-chunk result below.
      }
      return {started: true, receivedFirstChunk: false, errorName: ""};
    }

    // Abort only after Blink has delivered the server's first response bytes.
    // That requires Chromium to cancel an already-open HTTP/2 stream rather
    // than treating this as a pre-connect request rejection.
    controller.abort();
    let errorName = "";
    try {
      // A second read proves the already-open response body itself entered
      // the abort error state. A closed-stream promise alone would not
      // distinguish that from a generic stream-finalization path.
      await reader.read();
    } catch (error) {
      errorName = typeof error?.name === "string" ? error.name : "";
    }
    return {started: true, receivedFirstChunk: true, errorName};
  }

  async function readExactSlowStreamStage(reader, expected) {
    let received = "";
    while (received.length < expected.length) {
      const next = await reader.read();
      if (next.done) {
        return {ok: false, atMs: performance.now()};
      }
      received += new TextDecoder().decode(next.value);
    }
    return {ok: received === expected, atMs: performance.now()};
  }

  async function readExactSlowStreamConsumerBurst(reader) {
    let received = 0;
    while (received < slowStreamConsumerBurstBytes) {
      const next = await reader.read();
      if (next.done || next.value.length === 0 ||
          received + next.value.length > slowStreamConsumerBurstBytes) {
        return {ok: false, atMs: performance.now()};
      }
      for (const value of next.value) {
        if (value !== slowStreamConsumerBurstByte) {
          return {ok: false, atMs: performance.now()};
        }
      }
      received += next.value.length;
    }
    return {ok: true, atMs: performance.now()};
  }

  async function verifySlowStream() {
    const timerTicksBefore = state.timerTicks;
    const startedAt = performance.now();
    const result = {
      started: false,
      firstStage: false,
      secondStage: false,
      thirdStage: false,
      complete: false,
      proof: false,
      elapsedMs: 0,
      firstToSecondStageDelayMs: 0,
      secondToThirdStageDelayMs: 0,
      consumerPauseStarted: false,
      consumerBurstRead: false,
      consumerResume: false,
      consumerPauseElapsedMs: 0,
      consumerPauseTimerTicks: 0,
      timerTicksWhileWaiting: 0,
    };
    const finish = () => {
      result.elapsedMs = Math.floor(performance.now() - startedAt);
      result.timerTicksWhileWaiting = state.timerTicks - timerTicksBefore;
      state.slowStreamElapsedMs = result.elapsedMs;
      state.slowStreamFirstToSecondStageDelayMs =
          result.firstToSecondStageDelayMs;
      state.slowStreamSecondToThirdStageDelayMs =
          result.secondToThirdStageDelayMs;
      state.slowStreamConsumerPauseElapsedMs =
          result.consumerPauseElapsedMs;
      state.slowStreamConsumerPauseTimerTicks =
          result.consumerPauseTimerTicks;
      state.slowStreamTimerTicksWhileWaiting =
          result.timerTicksWhileWaiting;
      return result;
    };
    const response = await fetch(slowStreamURL, {
      cache: "no-store",
      credentials: "omit",
    });
    result.started = response.ok && !!response.body;
    state.slowStreamStarted = result.started;
    if (!result.started) {
      return finish();
    }

    const reader = response.body.getReader();
    const cancelOnFailure = async () => {
      try {
        await reader.cancel();
      } catch (_) {
        // The result below remains a failed staged-stream proof.
      }
    };
    const firstStage = await readExactSlowStreamStage(
        reader, slowStreamStages[0]);
    result.firstStage = firstStage.ok;
    state.slowStreamFirstStage = result.firstStage;
    if (!result.firstStage) {
      await cancelOnFailure();
      return finish();
    }
    const firstAck = await fetch(slowStreamFirstStageAckURL, {
      cache: "no-store",
      credentials: "omit",
    });
    if (!firstAck.ok || await firstAck.text() !==
        ${JSON.stringify(SLOW_STREAM_FIRST_STAGE_ACK_BODY)}) {
      await cancelOnFailure();
      return finish();
    }

    const secondStage = await readExactSlowStreamStage(
        reader, slowStreamStages[1]);
    result.secondStage = secondStage.ok;
    state.slowStreamSecondStage = result.secondStage;
    result.firstToSecondStageDelayMs = Math.floor(
        secondStage.atMs - firstStage.atMs);
    state.slowStreamFirstToSecondStageDelayMs =
        result.firstToSecondStageDelayMs;
    if (!result.secondStage) {
      await cancelOnFailure();
      return finish();
    }

    result.consumerPauseStarted = true;
    state.slowStreamConsumerPauseStarted = true;
    const pauseReady = await fetch(slowStreamConsumerPauseReadyURL, {
      cache: "no-store",
      credentials: "omit",
    });
    if (!pauseReady.ok || await pauseReady.text() !==
        ${JSON.stringify(SLOW_STREAM_CONSUMER_PAUSE_READY_BODY)}) {
      await cancelOnFailure();
      return finish();
    }
    const pauseTimerTicksBefore = state.timerTicks;
    const pauseStartedAt = performance.now();
    await new Promise((resolve) => setTimeout(resolve, slowStreamConsumerPauseMs));
    result.consumerPauseElapsedMs = Math.floor(
        performance.now() - pauseStartedAt);
    result.consumerPauseTimerTicks = state.timerTicks - pauseTimerTicksBefore;
    state.slowStreamConsumerPauseElapsedMs = result.consumerPauseElapsedMs;
    state.slowStreamConsumerPauseTimerTicks =
        result.consumerPauseTimerTicks;

    const burst = await readExactSlowStreamConsumerBurst(reader);
    result.consumerBurstRead = burst.ok;
    state.slowStreamConsumerBurstRead = result.consumerBurstRead;
    if (!result.consumerBurstRead) {
      await cancelOnFailure();
      return finish();
    }
    const consumerResume = await fetch(slowStreamConsumerResumeURL, {
      cache: "no-store",
      credentials: "omit",
    });
    result.consumerResume = consumerResume.ok && await consumerResume.text() ===
        ${JSON.stringify(SLOW_STREAM_CONSUMER_RESUME_BODY)};
    state.slowStreamConsumerResume = result.consumerResume;
    if (!result.consumerResume) {
      await cancelOnFailure();
      return finish();
    }

    const secondAck = await fetch(slowStreamSecondStageAckURL, {
      cache: "no-store",
      credentials: "omit",
    });
    if (!secondAck.ok || await secondAck.text() !==
        ${JSON.stringify(SLOW_STREAM_SECOND_STAGE_ACK_BODY)}) {
      await cancelOnFailure();
      return finish();
    }

    const thirdStage = await readExactSlowStreamStage(
        reader, slowStreamStages[2]);
    result.thirdStage = thirdStage.ok;
    state.slowStreamThirdStage = result.thirdStage;
    result.secondToThirdStageDelayMs = Math.floor(
        thirdStage.atMs - secondStage.atMs);
    state.slowStreamSecondToThirdStageDelayMs =
        result.secondToThirdStageDelayMs;
    if (!result.thirdStage) {
      await cancelOnFailure();
      return finish();
    }
    const completion = await reader.read();
    result.complete = completion.done === true;
    state.slowStreamComplete = result.complete;
    if (!result.complete) {
      await cancelOnFailure();
      return finish();
    }
    const proof = await fetch(slowStreamProofURL, {
      cache: "no-store",
      credentials: "omit",
    });
    result.proof = proof.ok && await proof.text() ===
        ${JSON.stringify(SLOW_STREAM_PROOF_BODY)};
    state.slowStreamProof = result.proof;
    return finish();
  }

  async function requestLargeDownload() {
    const frame = document.createElement("iframe");
    frame.hidden = true;
    frame.setAttribute("aria-hidden", "true");
    // Do not use Fetch or an anchor download attribute here. The attachment
    // response must become a navigation-owned DownloadItem in Chromium.
    state.largeDownloadNavigationRequested = true;
    frame.src = largeDownloadURL;
    document.body.appendChild(frame);
    await nativeDownloadComplete;
    return state.largeDownloadNativeComplete;
  }

  async function verifyWispMultiplex() {
    // Start both Fetches before awaiting either one. The two fixture handlers
    // hold their bodies until the relay has proved distinct, simultaneously
    // open WISP streams on its current WebSocket carrier.
    const h2Request = fetch(multiplexH2URL, {
      cache: "no-store",
      credentials: "omit",
    });
    const h1Request = fetch(multiplexH1URL, {
      cache: "no-store",
      credentials: "omit",
      mode: "cors",
    });
    state.multiplexRequestsStarted = true;
    const [h2Response, h1Response] = await Promise.all([h2Request, h1Request]);
    const [h2Body, h1Body] = await Promise.all([
      h2Response.text(),
      h1Response.text(),
    ]);
    return {
      h2Response: h2Response.ok && h2Body ===
          ${JSON.stringify(MULTIPLEX_H2_BODY)},
      h1Response: h1Response.ok && h1Body ===
          ${JSON.stringify(MULTIPLEX_H1_BODY)},
    };
  }

  async function verifyWispReconnect() {
    const result = {
      started: false,
      firstChunkReceived: false,
      firstChunkAck: false,
      disconnectRequested: false,
      streamFailed: false,
      streamErrorName: "",
      recovered: false,
      recoveryProtocol: "",
    };
    const response = await fetch(reconnectStreamURL, {
      cache: "no-store",
      credentials: "omit",
    });
    result.started = response.ok && !!response.body &&
        response.headers.get("content-length") ===
            String(reconnectStreamFirstChunk.length + 1);
    state.reconnectStreamStarted = result.started;
    if (!result.started) {
      return result;
    }

    const reader = response.body.getReader();
    let received = "";
    while (received.length < reconnectStreamFirstChunk.length) {
      const next = await reader.read();
      if (next.done) {
        return result;
      }
      received += new TextDecoder().decode(next.value);
    }
    result.firstChunkReceived = received === reconnectStreamFirstChunk;
    state.reconnectFirstChunkReceived = result.firstChunkReceived;
    if (!result.firstChunkReceived) {
      return result;
    }

    // The acknowledgement runs on the same H2 session as the partial body.
    // Its exact response proves the fixture received it before the delayed
    // RFC 6455 carrier close is armed; a bounded wait prevents a stalled
    // transport from being mislabeled as a reconnect.
    let ack = null;
    try {
      ack = await Promise.race([
        fetch(reconnectFirstChunkAckURL, {
          cache: "no-store",
          credentials: "omit",
        }),
        new Promise((resolve) => setTimeout(
            () => resolve(null), ${RECONNECT_ACK_TIMEOUT_MS})),
      ]);
    } catch (_) {
      return result;
    }
    let ackBody = "";
    try {
      ackBody = ack ? await ack.text() : "";
    } catch (_) {
      return result;
    }
    result.firstChunkAck = ack?.ok === true && ackBody ===
        ${JSON.stringify(RECONNECT_FIRST_CHUNK_ACK_BODY)};
    state.reconnectFirstChunkAck = result.firstChunkAck;
    if (!result.firstChunkAck) {
      return result;
    }

    // The accepted same-session ACK arms the fixture's close only after
    // Chromium has received the partial response.
    result.disconnectRequested = true;
    state.reconnectDisconnectRequested = true;

    // Wait for the deliberately incomplete old body to fail before issuing
    // recovery. A clean EOF or local abort is not a WISP transport failure.
    const streamFailure = reader.read().then(
        () => ({errorName: ""}),
        (error) => ({
          errorName: typeof error?.name === "string" ? error.name : "",
        }));
    const streamOutcome = await Promise.race([
      streamFailure,
      new Promise((resolve) => setTimeout(
          () => resolve({errorName: ""}),
          ${RECONNECT_STREAM_FAILURE_TIMEOUT_MS})),
    ]);
    result.streamErrorName = streamOutcome.errorName;
    result.streamFailed = result.streamErrorName === "TypeError";
    state.reconnectStreamErrorName = result.streamErrorName;
    state.reconnectStreamFailed = result.streamFailed;
    if (!result.streamFailed) {
      return result;
    }

    const recovery = await fetch(reconnectRecoveryURL, {
      cache: "no-store",
      credentials: "omit",
    });
    const recoveryBody = await recovery.text();
    result.recoveryProtocol = nextHopProtocol(reconnectRecoveryURL);
    result.recovered = recovery.ok && recoveryBody ===
        ${JSON.stringify(RECONNECT_RECOVERY_BODY)} &&
        result.recoveryProtocol === "h2";
    state.reconnectRecoveryProtocol = result.recoveryProtocol;
    state.reconnectRecovered = result.recovered;
    return result;
  }

  // The Content Shell observer accepts its deterministic probe through a
  // string-valued JavaScript execution callback. Keep the network work async,
  // but serialize this synchronous snapshot so each periodic observer probe
  // can report the fixture's current state once it completes.
  window.__chromiumWasmM5Probe = () => JSON.stringify({
    protocol: 1,
    fixture,
    ready: state.complete && state.timerTicks >= 3,
    phase: "https-fixture",
    timerTicks: state.timerTicks,
    h2Fetch: state.h2Fetch,
    h2Protocol: state.h2Protocol,
    localGatewayMappedRequestStarted: state.localGatewayMappedRequestStarted,
    localGatewayMappedResponse: state.localGatewayMappedResponse,
    localGatewayBlockedRequestStarted:
        state.localGatewayBlockedRequestStarted,
    localGatewayBlocked: state.localGatewayBlocked,
    cacheStored: state.cacheStored,
    cacheRevalidated: state.cacheRevalidated,
    cancelStreamStarted: state.cancelStreamStarted,
    cancelStreamReceivedFirstChunk: state.cancelStreamReceivedFirstChunk,
    cancelStreamAborted: state.cancelStreamAborted,
    cancelStreamErrorName: state.cancelStreamErrorName,
    cancelStreamProof: state.cancelStreamProof,
    slowStreamStarted: state.slowStreamStarted,
    slowStreamFirstStage: state.slowStreamFirstStage,
    slowStreamSecondStage: state.slowStreamSecondStage,
    slowStreamThirdStage: state.slowStreamThirdStage,
    slowStreamComplete: state.slowStreamComplete,
    slowStreamProof: state.slowStreamProof,
    slowStreamConsumerPauseStarted: state.slowStreamConsumerPauseStarted,
    slowStreamConsumerBurstRead: state.slowStreamConsumerBurstRead,
    slowStreamConsumerResume: state.slowStreamConsumerResume,
    slowStreamElapsedMs: state.slowStreamElapsedMs,
    slowStreamFirstToSecondStageDelayMs:
        state.slowStreamFirstToSecondStageDelayMs,
    slowStreamSecondToThirdStageDelayMs:
        state.slowStreamSecondToThirdStageDelayMs,
    slowStreamConsumerPauseElapsedMs:
        state.slowStreamConsumerPauseElapsedMs,
    slowStreamConsumerPauseTimerTicks:
        state.slowStreamConsumerPauseTimerTicks,
    slowStreamTimerTicksWhileWaiting: state.slowStreamTimerTicksWhileWaiting,
    multiplexRequestsStarted: state.multiplexRequestsStarted,
    multiplexH2Response: state.multiplexH2Response,
    multiplexH1Response: state.multiplexH1Response,
    multiplexComplete: state.multiplexComplete,
    largeDownloadNavigationRequested: state.largeDownloadNavigationRequested,
    largeDownloadNativeComplete: state.largeDownloadNativeComplete,
    reconnectStreamStarted: state.reconnectStreamStarted,
    reconnectFirstChunkReceived: state.reconnectFirstChunkReceived,
    reconnectFirstChunkAck: state.reconnectFirstChunkAck,
    reconnectDisconnectRequested: state.reconnectDisconnectRequested,
    reconnectStreamFailed: state.reconnectStreamFailed,
    reconnectStreamErrorName: state.reconnectStreamErrorName,
    reconnectRecovered: state.reconnectRecovered,
    reconnectRecoveryProtocol: state.reconnectRecoveryProtocol,
    activeMixedContentBlocked: state.activeMixedContentBlocked,
    activeMixedContentCspAllowed: state.activeMixedContentCspAllowed,
    activeMixedContentErrorName: state.activeMixedContentErrorName,
    activeMixedContentTargetUrl: mixedContentTargetURL,
    cspConnectSrcBlocked: state.cspConnectSrcBlocked,
    corsFetch: state.corsFetch,
    redirected: state.redirected,
    webSocketEcho: state.webSocketEcho,
    nonce,
    altSvcH3Advertised: state.altSvcH3Advertised,
  });

  (async () => {
    try {
      const h2Response = await fetch(h2ResourceURL, {cache: "no-store"});
      const h2Text = await h2Response.text();
      // Resource Timing reports the selected network protocol. The origin is
      // H2-only, so both this value and the response marker must be h2.
      state.h2Protocol = nextHopProtocol(h2ResourceURL);
      state.h2Fetch = h2Response.ok && h2Text === "M5_H2_OK" &&
          h2Response.headers.get("x-m5-http-version") === "h2" &&
          state.h2Protocol === "h2";
      state.altSvcH3Advertised =
          /(?:^|,)\\s*h3=/.test(h2Response.headers.get("alt-svc") || "");

      const localGatewayResult = await verifyLocalGatewayRoute();
      if (!localGatewayResult.mappedRequestStarted ||
          !localGatewayResult.mappedResponse ||
          !localGatewayResult.blockedRequestStarted ||
          !localGatewayResult.blocked) {
        throw new Error("M5 local WISP gateway route proof failed");
      }

      // Fetch the first response with reload so this page always creates a
      // cache entry. The second request must revalidate that entry instead of
      // being satisfied as a fresh cache hit; the relay records the exact 304.
      const cacheStoreResponse = await fetch(cacheRevalidateURL, {
        cache: "reload",
        // This cache behavior must not depend on the redirect fixture's
        // HttpOnly cookie. Chromium still owns the cache entry and validator.
        credentials: "omit",
      });
      const cacheStoreText = await cacheStoreResponse.text();
      state.cacheStored = cacheStoreResponse.ok &&
          cacheStoreText === ${JSON.stringify(CACHE_REVALIDATE_BODY)} &&
          cacheStoreResponse.headers.get("etag") === cacheRevalidateETag;
      const cacheRevalidateResponse = await fetch(cacheRevalidateURL, {
        cache: "no-cache",
        credentials: "omit",
      });
      const cacheRevalidateText = await cacheRevalidateResponse.text();
      state.cacheRevalidated = state.cacheStored &&
          cacheRevalidateResponse.ok &&
          cacheRevalidateText === ${JSON.stringify(CACHE_REVALIDATE_BODY)} &&
          cacheRevalidateResponse.headers.get("etag") === cacheRevalidateETag;

      state.cspConnectSrcBlocked = await verifyCspConnectSrcBlock();
      if (!state.cspConnectSrcBlocked) {
        throw new Error("M5 CSP connect-src target was not blocked");
      }
      const cspProofResponse = await fetch(cspConnectSrcProofURL, {
        cache: "no-store",
        credentials: "omit",
      });
      if (!cspProofResponse.ok ||
          await cspProofResponse.text() !== "M5_CSP_CONNECT_SRC_PROOF") {
        throw new Error("M5 CSP connect-src proof failed");
      }

      const mixedContentResult = await verifyActiveMixedContentBlock();
      state.activeMixedContentCspAllowed = mixedContentResult.cspAllowed;
      state.activeMixedContentErrorName = mixedContentResult.errorName;
      if (!state.activeMixedContentCspAllowed ||
          state.activeMixedContentErrorName !== "TypeError") {
        throw new Error("M5 active mixed-content target was not blocked");
      }
      const mixedContentProofResponse = await fetch(mixedContentProofURL, {
        cache: "no-store",
        credentials: "omit",
      });
      if (!mixedContentProofResponse.ok ||
          await mixedContentProofResponse.text() !== "M5_MIXED_CONTENT_PROOF") {
        throw new Error("M5 mixed-content proof failed");
      }
      state.activeMixedContentBlocked = true;

      const cancelStreamResult = await verifyCancelStream();
      state.cancelStreamStarted = cancelStreamResult.started;
      state.cancelStreamReceivedFirstChunk =
          cancelStreamResult.receivedFirstChunk;
      state.cancelStreamErrorName = cancelStreamResult.errorName;
      state.cancelStreamAborted = state.cancelStreamStarted &&
          state.cancelStreamReceivedFirstChunk &&
          state.cancelStreamErrorName === "AbortError";
      if (!state.cancelStreamAborted) {
        throw new Error("M5 cancel stream was not aborted by Blink");
      }
      const cancelProofResponse = await fetch(cancelStreamProofURL, {
        cache: "no-store",
        credentials: "omit",
      });
      if (!cancelProofResponse.ok ||
          await cancelProofResponse.text() !==
              ${JSON.stringify(CANCEL_STREAM_PROOF_BODY)}) {
        throw new Error("M5 cancel stream proof failed");
      }
      state.cancelStreamProof = true;

      const slowStreamResult = await verifySlowStream();
      state.slowStreamStarted = slowStreamResult.started;
      state.slowStreamFirstStage = slowStreamResult.firstStage;
      state.slowStreamSecondStage = slowStreamResult.secondStage;
      state.slowStreamThirdStage = slowStreamResult.thirdStage;
      state.slowStreamComplete = slowStreamResult.complete;
      state.slowStreamProof = slowStreamResult.proof;
      state.slowStreamConsumerPauseStarted =
          slowStreamResult.consumerPauseStarted;
      state.slowStreamConsumerBurstRead = slowStreamResult.consumerBurstRead;
      state.slowStreamConsumerResume = slowStreamResult.consumerResume;
      state.slowStreamElapsedMs = slowStreamResult.elapsedMs;
      state.slowStreamFirstToSecondStageDelayMs =
          slowStreamResult.firstToSecondStageDelayMs;
      state.slowStreamSecondToThirdStageDelayMs =
          slowStreamResult.secondToThirdStageDelayMs;
      state.slowStreamConsumerPauseElapsedMs =
          slowStreamResult.consumerPauseElapsedMs;
      state.slowStreamConsumerPauseTimerTicks =
          slowStreamResult.consumerPauseTimerTicks;
      state.slowStreamTimerTicksWhileWaiting =
          slowStreamResult.timerTicksWhileWaiting;
      if (!state.slowStreamStarted || !state.slowStreamFirstStage ||
          !state.slowStreamSecondStage || !state.slowStreamThirdStage ||
          !state.slowStreamComplete || !state.slowStreamProof ||
          !state.slowStreamConsumerPauseStarted ||
          !state.slowStreamConsumerBurstRead ||
          !state.slowStreamConsumerResume) {
        throw new Error("M5 slow producer/consumer stream failed");
      }

      const multiplexResult = await verifyWispMultiplex();
      state.multiplexH2Response = multiplexResult.h2Response;
      state.multiplexH1Response = multiplexResult.h1Response;
      state.multiplexComplete = state.multiplexRequestsStarted &&
          state.multiplexH2Response && state.multiplexH1Response;
      if (!state.multiplexComplete) {
        throw new Error("M5 live WISP multiplex stream proof failed");
      }

      if (!await requestLargeDownload()) {
        throw new Error("M5 native attachment download did not complete");
      }

      const reconnectResult = await verifyWispReconnect();
      state.reconnectStreamStarted = reconnectResult.started;
      state.reconnectFirstChunkReceived = reconnectResult.firstChunkReceived;
      state.reconnectFirstChunkAck = reconnectResult.firstChunkAck;
      state.reconnectDisconnectRequested = reconnectResult.disconnectRequested;
      state.reconnectStreamFailed = reconnectResult.streamFailed;
      state.reconnectStreamErrorName = reconnectResult.streamErrorName;
      state.reconnectRecovered = reconnectResult.recovered;
      state.reconnectRecoveryProtocol = reconnectResult.recoveryProtocol;
      if (!state.reconnectStreamStarted ||
          !state.reconnectFirstChunkReceived ||
          !state.reconnectFirstChunkAck ||
          !state.reconnectDisconnectRequested ||
          !state.reconnectStreamFailed ||
          !state.reconnectRecovered ||
          state.reconnectRecoveryProtocol !== "h2") {
        throw new Error("M5 WISP reconnect failed");
      }

      const corsResponse = await fetch(corsURL, {
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
      });
      state.corsFetch = corsResponse.ok &&
          await corsResponse.text() === "M5_CORS_OK";
      state.webSocketEcho = await echoNonce();
      state.complete = state.h2Fetch && state.altSvcH3Advertised &&
          state.localGatewayMappedRequestStarted &&
          state.localGatewayMappedResponse &&
          state.localGatewayBlockedRequestStarted &&
          state.localGatewayBlocked &&
          state.cacheStored && state.cacheRevalidated &&
          state.cspConnectSrcBlocked && state.activeMixedContentBlocked &&
          state.cancelStreamStarted && state.cancelStreamReceivedFirstChunk &&
          state.cancelStreamAborted && state.cancelStreamProof &&
          state.slowStreamStarted && state.slowStreamFirstStage &&
          state.slowStreamSecondStage && state.slowStreamThirdStage &&
          state.slowStreamComplete && state.slowStreamProof &&
          state.slowStreamConsumerPauseStarted &&
          state.slowStreamConsumerBurstRead &&
          state.slowStreamConsumerResume &&
          state.multiplexRequestsStarted &&
          state.multiplexH2Response && state.multiplexH1Response &&
          state.multiplexComplete &&
          state.largeDownloadNavigationRequested &&
          state.largeDownloadNativeComplete &&
          state.reconnectStreamStarted &&
          state.reconnectFirstChunkReceived &&
          state.reconnectFirstChunkAck &&
          state.reconnectDisconnectRequested &&
          state.reconnectStreamFailed &&
          state.reconnectRecovered &&
          state.reconnectRecoveryProtocol === "h2" &&
          state.corsFetch && state.redirected && state.webSocketEcho;
      status.textContent = state.complete ?
        "Chromium M5 local-gateway/redirect/cache/CSP/mixed/cancel/slow/multiplex/download/reconnect/TCP/H2/CORS/WebSocket checks passed." :
        "Chromium M5 network checks did not complete.";
    } catch (_) {
      state.failure = "network-check-failed";
      status.textContent = "Chromium M5 network checks failed.";
    }
  })();
})();
</script>`;
}

function hasExpectedRedirectCookie(headers, context) {
  const header = headers.cookie;
  const cookieLine = Array.isArray(header) ? header.join(";") : header;
  if (typeof cookieLine !== "string") {
    return false;
  }
  return cookieLine.split(";").some((entry) => {
    const separator = entry.indexOf("=");
    return separator > 0 &&
        entry.slice(0, separator).trim() === REDIRECT_COOKIE_NAME &&
        entry.slice(separator + 1).trim() === context.redirectCookieValue;
  });
}

function createH2Server(context, tlsMaterial) {
  const server = http2.createSecureServer({
    allowHTTP1: false,
    cert: tlsMaterial,
    key: tlsMaterial,
  });
  server.on("stream", (stream, headers) => {
    const method = headers[":method"];
    const requestPath = headers[":path"];
    if (method !== "GET") {
      stream.respond(h2Headers({":status": 405}));
      stream.end();
      return;
    }
    context.stats.h2Requests += 1;
    if (requestPath === "/m5/redirect-cookie") {
      context.stats.redirectRequests += 1;
      stream.respond(h2Headers({
        ":status": 302,
        "location": "/m5/",
        "set-cookie":
          `${REDIRECT_COOKIE_NAME}=${context.redirectCookieValue}; ` +
          "Secure; HttpOnly; SameSite=Strict; Path=/m5/",
      }));
      stream.end();
      // Never include the opaque cookie value in status or transcript data.
      context.transcript.add("h2-redirect");
      context.transcript.add("h2-redirect-cookie");
      return;
    }
    if (requestPath === "/m5/") {
      if (!hasExpectedRedirectCookie(headers, context)) {
        const body = Buffer.from("M5_REDIRECT_COOKIE_REJECTED");
        stream.respond(h2Headers({
          ":status": 403,
          "content-length": String(body.length),
          "content-type": "text/plain; charset=utf-8",
        }));
        stream.end(body);
        context.transcript.add("h2-page-cookie-rejected");
        return;
      }
      context.stats.redirectCookieValidations += 1;
      const body = Buffer.from(h2Page(context));
      stream.respond(h2Headers({
        ":status": 200,
        "content-length": String(body.length),
        "content-type": "text/html; charset=utf-8",
        "content-security-policy":
          "default-src 'self'; connect-src 'self' https://" +
          TEST_HOSTNAME + ":" + context.h1Port + " wss://" +
          TEST_HOSTNAME + ":" + context.h1Port + " http://" +
          TEST_HOSTNAME + ":" + context.plaintextHttpControlPort +
          " https://" + TEST_HOSTNAME + ":" +
          LOCAL_GATEWAY_HTTPS_PORT + " https://" + TEST_HOSTNAME + ":" +
          LOCAL_GATEWAY_BLOCKED_PORT +
          "; base-uri 'none'; object-src 'none'; script-src 'unsafe-inline'; " +
          "style-src 'unsafe-inline'",
      }));
      stream.end(body);
      context.transcript.add("h2-page");
      context.transcript.add("h2-page-cookie");
      return;
    }
    if (requestPath === "/m5/cache-revalidate") {
      const ifNoneMatch = headers["if-none-match"];
      if (ifNoneMatch === undefined) {
        const body = Buffer.from(CACHE_REVALIDATE_BODY);
        incrementBoundedCounter(context, "cacheStore200s");
        stream.respond(h2Headers({
          ":status": 200,
          "cache-control": CACHE_REVALIDATE_CACHE_CONTROL,
          "content-length": String(body.length),
          "content-type": "text/plain; charset=utf-8",
          "etag": CACHE_REVALIDATE_ETAG,
          "x-m5-cache-state": "stored",
        }));
        stream.end(body);
        context.transcript.add("h2-cache-store-200");
        return;
      }

      incrementBoundedCounter(context, "cacheConditionalRequests");
      if (ifNoneMatch !== CACHE_REVALIDATE_ETAG) {
        const body = Buffer.from("M5_CACHE_REVALIDATE_UNEXPECTED");
        incrementBoundedCounter(context, "cacheUnexpectedRequests");
        stream.respond(h2Headers({
          ":status": 400,
          "content-length": String(body.length),
          "content-type": "text/plain; charset=utf-8",
        }));
        stream.end(body);
        context.transcript.add("h2-cache-revalidate-unexpected");
        return;
      }

      incrementBoundedCounter(context, "cacheNotModified304s");
      stream.respond(h2Headers({
        ":status": 304,
        "cache-control": CACHE_REVALIDATE_CACHE_CONTROL,
        "etag": CACHE_REVALIDATE_ETAG,
        "x-m5-cache-state": "revalidated",
      }));
      stream.end();
      context.transcript.add("h2-cache-revalidate-304");
      return;
    }
    if (requestPath === "/m5/csp-connect-src-proof") {
      const body = Buffer.from("M5_CSP_CONNECT_SRC_PROOF");
      incrementBoundedCounter(context, "cspConnectSrcProofs");
      stream.respond(h2Headers({
        ":status": 200,
        "content-length": String(body.length),
        "content-type": "text/plain; charset=utf-8",
      }));
      stream.end(body);
      context.transcript.add("h2-csp-connect-src-proof");
      return;
    }
    if (requestPath === "/m5/mixed-content-proof") {
      const body = Buffer.from("M5_MIXED_CONTENT_PROOF");
      incrementBoundedCounter(context, "mixedContentProofs");
      stream.respond(h2Headers({
        ":status": 200,
        "content-length": String(body.length),
        "content-type": "text/plain; charset=utf-8",
      }));
      stream.end(body);
      context.transcript.add("h2-mixed-content-proof");
      return;
    }
    if (requestPath === "/m5/cancel-stream") {
      incrementBoundedCounter(context, "cancelStreamRequests");
      if (context.cancelStreamPhase !== "pre-cancel") {
        const body = Buffer.from("M5_CANCEL_STREAM_REJECTED");
        stream.respond(h2Headers({
          ":status": 409,
          "content-length": String(body.length),
          "content-type": "text/plain; charset=utf-8",
          "x-m5-cancel-stream": "duplicate",
        }));
        stream.end(body);
        context.transcript.add("h2-cancel-stream-rejected");
        return;
      }

      context.cancelStreamPhase = "streaming";
      context.cancelStreamSession = stream.session;
      const firstChunk = Buffer.from(CANCEL_STREAM_FIRST_CHUNK);
      stream.respond(h2Headers({
        ":status": 200,
        "content-type": "text/plain; charset=utf-8",
        "x-m5-cancel-stream": "streaming",
      }));
      stream.write(firstChunk);
      incrementBoundedCounter(context, "cancelStreamFirstChunks");
      context.transcript.add("h2-cancel-stream-start");

      let resetObserved = false;
      const observeReset = () => {
        if (resetObserved || context.cancelStreamPhase !== "streaming") {
          return;
        }
        resetObserved = true;
        if (stream.rstCode === http2.constants.NGHTTP2_CANCEL) {
          context.cancelStreamPhase = "cancel-observed";
          incrementBoundedCounter(context, "cancelStreamCancelResets");
          context.transcript.add("h2-cancel-stream-cancel-reset", {
            rstCode: stream.rstCode,
          });
          resolvePendingCancelStreamProofs(context, true);
          return;
        }
        context.cancelStreamPhase = "unexpected-reset";
        incrementBoundedCounter(context, "cancelStreamUnexpectedResets");
        context.transcript.add("h2-cancel-stream-unexpected-reset", {
          rstCode: stream.rstCode,
        });
        resolvePendingCancelStreamProofs(context, false);
      };
      // Node reports peer-initiated RST_STREAM through `aborted`, then closes
      // the stream. Listen to both so the state remains deterministic across
      // supported Node versions while accepting only the HTTP/2 CANCEL code.
      stream.once("aborted", observeReset);
      stream.once("close", observeReset);
      stream.once("error", observeReset);
      return;
    }
    if (requestPath === "/m5/cancel-proof") {
      if (!isCancelStreamProofSession(context, stream)) {
        rejectCancelStreamProofSessionMismatch(stream, context);
      } else if (context.cancelStreamPhase === "cancel-observed") {
        respondToCancelStreamProof(stream, context, true);
      } else if (context.cancelStreamPhase === "streaming") {
        // The page can issue this proof immediately after AbortController
        // settles. Hold one bounded request until Node has observed the
        // corresponding HTTP/2 reset instead of relying on a timer in Blink.
        holdCancelStreamProof(context, stream);
      } else {
        respondToCancelStreamProof(stream, context, false);
      }
      return;
    }
    if (requestPath === "/m5/slow-stream") {
      incrementBoundedCounter(context, "slowStreamRequests");
      if (context.slowStreamPhase !== "pre-stream") {
        context.transcript.add("h2-slow-stream-rejected");
        respondToSlowStreamControl(
            stream, 409, "M5_SLOW_STREAM_REJECTED", "duplicate");
        return;
      }

      context.slowStreamSession = stream.session;
      context.slowStreamResponse = stream;
      context.slowStreamPhase = "opening";
      context.transcript.add("h2-slow-stream-start");
      let closeObserved = false;
      const observeClose = () => {
        if (closeObserved) {
          return;
        }
        closeObserved = true;
        clearSlowStreamStageTimer(context);
        clearSlowStreamStageAckTimeout(context);
        if (context.slowStreamPhase === "complete" ||
            context.slowStreamPhase === "stage-ack-timeout" ||
            context.slowStreamPhase === "unexpected-close") {
          return;
        }
        context.slowStreamPhase = "unexpected-close";
        incrementBoundedCounter(context, "slowStreamUnexpectedCloses");
        context.transcript.add("h2-slow-stream-unexpected-close");
      };
      stream.once("aborted", observeClose);
      stream.once("close", observeClose);
      stream.once("error", observeClose);
      if (!writeSlowStreamStage(context, 0)) {
        context.slowStreamPhase = "unexpected-close";
        incrementBoundedCounter(context, "slowStreamUnexpectedCloses");
        context.transcript.add("h2-slow-stream-unexpected-close");
      }
      return;
    }
    if (requestPath === "/m5/slow-stream-first-stage-ack") {
      handleSlowStreamStageAck(stream, context, 0);
      return;
    }
    if (requestPath === "/m5/slow-stream-second-stage-ack") {
      handleSlowStreamStageAck(stream, context, 1);
      return;
    }
    if (requestPath === "/m5/slow-stream-consumer-pause-ready") {
      handleSlowStreamConsumerPauseReady(stream, context);
      return;
    }
    if (requestPath === "/m5/slow-stream-consumer-resume") {
      handleSlowStreamConsumerResume(stream, context);
      return;
    }
    if (requestPath === "/m5/slow-stream-proof") {
      handleSlowStreamProof(stream, context);
      return;
    }
    if (requestPath === "/m5/multiplex-h2") {
      handleMultiplexH2Request(stream, context);
      return;
    }
    if (requestPath === "/m5/large-download") {
      writeLargeDownload(context, stream);
      return;
    }
    if (requestPath === "/m5/reconnect-stream") {
      writeReconnectStream(context, stream);
      return;
    }
    if (requestPath === "/m5/reconnect-first-chunk-ack") {
      handleReconnectFirstChunkAck(stream, context);
      return;
    }
    if (requestPath === "/m5/reconnect-recovery") {
      handleReconnectRecovery(stream, context);
      return;
    }
    if (requestPath === "/m5/local-gateway-probe") {
      handleLocalGatewayProbe(stream, context);
      return;
    }
    if (requestPath === "/m5/h2-resource") {
      const body = Buffer.from("M5_H2_OK");
      stream.respond(h2Headers({
        ":status": 200,
        "content-length": String(body.length),
        "content-type": "text/plain; charset=utf-8",
        "x-m5-http-version": "h2",
      }));
      stream.end(body);
      context.transcript.add("h2-resource");
      return;
    }
    stream.respond(h2Headers({":status": 404}));
    stream.end();
  });
  server.on("session", (session) => {
    context.h2Sessions.add(session);
    session.once("close", () => context.h2Sessions.delete(session));
  });
  return server;
}

function createTlsFailureServer(context, tlsMaterial) {
  // Certificate selection happens during TLS, before HTTP routing. Keep this
  // endpoint on a distinct loopback port so the normal a.test H2 route can
  // retain its valid test_names.pem certificate while this route presents the
  // trusted-but-wrong-name localhost certificate.
  const server = http2.createSecureServer({
    allowHTTP1: false,
    cert: tlsMaterial,
    key: tlsMaterial,
  });
  server.on("connection", (socket) => {
    context.tlsFailureSockets.add(socket);
    socket.once("close", () => context.tlsFailureSockets.delete(socket));
    context.stats.tlsMismatchTcpConnections += 1;
    // A validating TLS client normally closes after receiving the
    // certificate, before Node emits a completed TLS session. TCP connection
    // evidence is therefore intentional; do not mistake it for handshake
    // success.
    context.transcript.add("tls-failure-tcp-connect");
  });
  server.on("stream", (stream, headers) => {
    context.stats.tlsMismatchHttpStreams += 1;
    context.transcript.add("tls-failure-http-request");

    // No normal M5 run may reach this handler. If certificate validation were
    // incorrectly bypassed, make the controlled cross-origin response
    // readable by the successful page so its fetch cannot look like a CORS
    // failure instead of a TLS regression.
    const pageOrigin = `https://${TEST_HOSTNAME}:${context.h2Port}`;
    const expectedRequest = headers[":method"] === "GET" &&
        headers[":path"] === "/m5/tls-name-mismatch";
    const body = Buffer.from(expectedRequest
        ? "M5_TLS_NAME_MISMATCH_UNEXPECTED"
        : "M5_TLS_FAILURE_ENDPOINT_UNEXPECTED_REQUEST");
    stream.respond({
      ":status": expectedRequest ? 200 : 404,
      "access-control-allow-origin": pageOrigin,
      "cache-control": "no-store",
      "content-length": String(body.length),
      "content-type": "text/plain; charset=utf-8",
      "vary": "Origin",
      "x-content-type-options": "nosniff",
      "x-m5-tls-failure-endpoint": "reached",
    });
    stream.end(body);
  });
  server.on("session", (session) => {
    context.h2Sessions.add(session);
    session.once("close", () => context.h2Sessions.delete(session));
  });
  return server;
}

function createCspConnectSrcTargetServer(context, tlsMaterial) {
  // This target has a valid a.test certificate and a CORS-readable response.
  // It is omitted from the fixture page's connect-src directive, so an M5
  // browser run must never establish this connection or reach this handler.
  const server = https.createServer({cert: tlsMaterial, key: tlsMaterial},
      (request, response) => {
        const pageOrigin = `https://${TEST_HOSTNAME}:${context.h2Port}`;
        const expectedRequest = request.method === "GET" &&
            request.url === "/m5/csp-connect-src-target" &&
            request.headers.origin === pageOrigin;
        incrementBoundedCounter(context, "cspConnectSrcTargetRequests");
        context.transcript.add("h1-csp-connect-src-target-request");
        const body = expectedRequest
          ? "M5_CSP_CONNECT_SRC_TARGET_UNEXPECTED"
          : "M5_CSP_CONNECT_SRC_TARGET_BAD_REQUEST";
        response.writeHead(expectedRequest ? 200 : 404, {
          "Access-Control-Allow-Origin": pageOrigin,
          "Cache-Control": "no-store",
          "Connection": "close",
          "Content-Length": Buffer.byteLength(body),
          "Content-Type": "text/plain; charset=utf-8",
          "Vary": "Origin",
          "X-Content-Type-Options": "nosniff",
          "X-M5-CSP-Connect-Src-Target": "reached",
        });
        response.end(body);
      });
  server.on("connection", (socket) => {
    context.cspConnectSrcTargetSockets.add(socket);
    socket.once("close", () => context.cspConnectSrcTargetSockets.delete(socket));
    incrementBoundedCounter(context, "cspConnectSrcTargetTcpConnections");
    context.transcript.add("csp-connect-src-target-tcp-connect");
  });
  return server;
}

function writePlaintextHttpResponse(response, status, body, extra = {}) {
  const bytes = Buffer.isBuffer(body) ? body : Buffer.from(body);
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Connection": "close",
    "Content-Length": String(bytes.length),
    "Content-Type": "text/plain; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "X-M5-HTTP-Version": "http/1.1",
    ...extra,
  });
  response.end(bytes);
}

function plaintextHttpControlPage() {
  return [
    "<!doctype html>",
    '<meta charset="utf-8">',
    "<title>Chromium Wasm M5 plaintext control</title>",
    "<style>body{font:16px sans-serif;margin:2rem}#m5-status{white-space:pre-wrap}</style>",
    "<h1>Chromium Wasm M5 plaintext control</h1>",
    '<p id="m5-status">Proving Chromium plaintext HTTP transport…</p>',
    "<script>",
    "(() => {",
    '  "use strict";',
    "  const fixture = " + JSON.stringify(FIXTURE) + ";",
    "  const proofURL =",
    '      new URL("/m5/plaintext-control-proof", location.href).href;',
    "  const state = {",
    "    timerTicks: 0,",
    "    plaintextHttpControlProof: false,",
    "    failure: null,",
    "  };",
    '  const status = document.querySelector("#m5-status");',
    "  setInterval(() => {",
    "    state.timerTicks = Math.min(state.timerTicks + 1, 1000);",
    "  }, 25);",
    "",
    "  window.__chromiumWasmM5PlaintextHttpControlProbe = () => JSON.stringify({",
    "    protocol: 1,",
    "    fixture,",
    "    ready: state.plaintextHttpControlProof && state.timerTicks >= 3,",
    '    phase: "plaintext-http-control",',
    "    timerTicks: state.timerTicks,",
    "    plaintextHttpControlDocument: true,",
    "    plaintextHttpControlProof: state.plaintextHttpControlProof,",
    "  });",
    "",
    "  (async () => {",
    "    try {",
    "      const response = await fetch(proofURL, {",
    '        cache: "no-store",',
    '        credentials: "omit",',
    "      });",
    "      state.plaintextHttpControlProof = response.ok &&",
    '          await response.text() === "M5_PLAINTEXT_CONTROL_PROOF";',
    "      if (!state.plaintextHttpControlProof) {",
    '        throw new Error("M5 plaintext control proof failed");',
    "      }",
    '      status.textContent = "Chromium plaintext HTTP control passed.";',
    "    } catch (_) {",
    '      state.failure = "plaintext-control-failed";',
    '      status.textContent = "Chromium plaintext HTTP control failed.";',
    "    }",
    "  })();",
    "})();",
    "</script>",
  ].join("\n");
}

function createPlaintextHttpControlServer(context) {
  const server = http.createServer((request, response) => {
    const pageOrigin = "https://" + TEST_HOSTNAME + ":" + context.h2Port;
    const isControlDocument = request.method === "GET" &&
        request.url === "/m5/plaintext-control";
    const isControlProof = request.method === "GET" &&
        request.url === "/m5/plaintext-control-proof";
    const isMixedContentTarget = request.method === "GET" &&
        request.url === "/m5/mixed-content-target";

    if (isControlDocument) {
      if (context.plaintextHttpControlPhase !== "pre-control") {
        writePlaintextHttpResponse(
            response, 409, "M5_PLAINTEXT_CONTROL_PHASE_COMPLETE", {
              "X-M5-Plaintext-Control": "phase-complete",
            });
        return;
      }
      context.plaintextHttpControlDocumentServed = true;
      incrementBoundedCounter(context, "plaintextHttpControlRequests");
      context.transcript.add("h1-plaintext-http-control");
      writePlaintextHttpResponse(response, 200, plaintextHttpControlPage(), {
        "Content-Security-Policy":
          "default-src 'self'; base-uri 'none'; object-src 'none'; " +
          "connect-src 'self'; script-src 'unsafe-inline'; " +
          "style-src 'unsafe-inline'",
        "Content-Type": "text/html; charset=utf-8",
        "X-M5-Plaintext-Control": "document",
      });
      return;
    }

    if (isControlProof) {
      if (context.plaintextHttpControlPhase !== "pre-control" ||
          !context.plaintextHttpControlDocumentServed) {
        writePlaintextHttpResponse(
            response, 409, "M5_PLAINTEXT_CONTROL_PROOF_REJECTED", {
              "X-M5-Plaintext-Control": "proof-rejected",
            });
        return;
      }
      incrementBoundedCounter(context, "plaintextHttpControlProofs");
      context.transcript.add("h1-plaintext-http-control-proof");
      context.plaintextHttpControlPhase = "post-control";
      context.transcript.add("plaintext-http-control-phase-complete");
      writePlaintextHttpResponse(response, 200, "M5_PLAINTEXT_CONTROL_PROOF", {
        "X-M5-Plaintext-Control": "proof",
      });
      return;
    }

    if (isMixedContentTarget) {
      const reachedAfterControl =
          context.plaintextHttpControlPhase === "post-control";
      if (reachedAfterControl) {
        incrementBoundedCounter(
            context, "mixedContentTargetPostControlRequests");
        context.transcript.add(
            "h1-mixed-content-target-post-control-request");
      }
      const expectedRequest = request.headers.origin === pageOrigin;
      writePlaintextHttpResponse(
          response, expectedRequest ? 200 : 404,
          expectedRequest ? "M5_MIXED_CONTENT_TARGET_UNEXPECTED" :
            "M5_MIXED_CONTENT_TARGET_BAD_REQUEST", {
            "Access-Control-Allow-Origin": pageOrigin,
            "Vary": "Origin",
            "X-M5-Mixed-Content-Target": "reached",
          });
      return;
    }

    writePlaintextHttpResponse(response, 404, "M5_PLAINTEXT_HTTP_NOT_FOUND");
  });
  server.on("connection", (socket) => {
    context.plaintextHttpControlSockets.add(socket);
    socket.once("close", () => context.plaintextHttpControlSockets.delete(socket));
    if (context.plaintextHttpControlPhase === "pre-control") {
      incrementBoundedCounter(context, "plaintextHttpControlTcpConnections");
      context.transcript.add("plaintext-http-control-tcp-connect");
      return;
    }
    // Once the control proof flips phase, no WISP/TCP connection to this same
    // listener is expected. The listener cannot know a request path yet, so
    // this catches an attempted mixed-content route before HTTP parsing.
    incrementBoundedCounter(
        context, "mixedContentTargetPostControlTcpConnections");
    context.transcript.add("mixed-content-target-post-control-tcp-connect");
  });
  return server;
}

function createH1Server(context, tlsMaterial) {
  const server = https.createServer({cert: tlsMaterial, key: tlsMaterial},
      (request, response) => {
        const pageOrigin = `https://${TEST_HOSTNAME}:${context.h2Port}`;
        if (request.method === "GET" && request.url === "/m5/multiplex-h1") {
          handleMultiplexH1Request(request, response, context);
          return;
        }
        if (request.method === "GET" && request.url === "/m5/cors-resource" &&
            request.headers.origin === pageOrigin) {
          const body = "M5_CORS_OK";
          response.writeHead(200, {
            "Access-Control-Allow-Origin": pageOrigin,
            "Cache-Control": "no-store",
            // Keep the CORS fetch and the subsequent WSS upgrade on distinct
            // Chromium TCP/WISP streams, which makes the transcript prove
            // both HTTP/1.1 and WebSocket connection setup.
            "Connection": "close",
            "Content-Length": Buffer.byteLength(body),
            "Content-Type": "text/plain; charset=utf-8",
            "Vary": "Origin",
            "X-Content-Type-Options": "nosniff",
            "X-M5-HTTP-Version": "http/1.1",
          });
          response.end(body);
          context.transcript.add("h1-cors");
          context.stats.corsRequests += 1;
          return;
        }
        response.writeHead(404, {
          "Cache-Control": "no-store",
          "Content-Length": "0",
          "X-Content-Type-Options": "nosniff",
        });
        response.end();
      });
  server.on("upgrade", (request, socket, head) => {
    const pageOrigin = `https://${TEST_HOSTNAME}:${context.h2Port}`;
    let peer = null;
    peer = acceptWebSocketUpgrade(request, socket, head, {
      allowText: true,
      expectedOrigin: pageOrigin,
      path: "/m5/ws",
      onClosed: () => {
        if (peer) {
          context.echoPeers.delete(peer);
          context.transcript.add("h1-wss-close");
        }
      },
      onMessage: ({opcode, payload}) => {
        if (payload.length > MAX_ECHO_MESSAGE_BYTES) {
          peer.close(1009, "echo-limit");
          return;
        }
        peer.send(opcode, payload);
        context.stats.webSocketEchoes += 1;
        context.transcript.add("h1-wss-echo", {bytes: payload.length});
      },
    });
    if (peer) {
      context.echoPeers.add(peer);
      context.transcript.add("h1-wss-open");
    }
  });
  return server;
}

function createWispServer(context) {
  const server = http.createServer((request, response) => {
    if (request.method === "GET" && request.url === STATUS_PATH) {
      writeJson(response, 200, statusSnapshot(context));
      return;
    }
    response.writeHead(404, {
      "Cache-Control": "no-store",
      "Content-Length": "0",
      "X-Content-Type-Options": "nosniff",
    });
    response.end();
  });
  server.on("upgrade", (request, socket, head) => {
    let relay = null;
    let peer = null;
    peer = acceptWebSocketUpgrade(request, socket, head, {
      allowText: false,
      expectedOrigin: context.hostOrigin,
      path: WISP_PATH,
      subprotocol: "wisp",
      onClosed: () => {
        if (relay) {
          relay.close();
        }
      },
      onWritable: () => relay?.writable(),
      onMessage: (message) => relay?.receive(message),
    });
    if (!peer) {
      context.transcript.add("wisp-upgrade-rejected");
      return;
    }
    relay = new WispRelay(peer, context, () => context.relays.delete(relay));
    context.relays.add(relay);
  });
  // Upgraded sockets leave HTTP's normal keep-alive accounting. Keep explicit
  // ownership so a client that receives a close frame but never sends its TCP
  // FIN cannot make the fixture or a browser smoke wait indefinitely.
  server.on("connection", (socket) => {
    context.wispSockets.add(socket);
    socket.once("close", () => context.wispSockets.delete(socket));
  });
  return server;
}

function statusSummary(context, reason) {
  return {
    event: "m5-wisp-test-server-shutdown",
    fixture: FIXTURE,
    protocol: 1,
    reason,
    ...statusSnapshot(context),
  };
}

async function start(options) {
  // These PEMs contain test server keys as well as certificates. They are read
  // only by loopback TLS listeners and are never serialized into page content,
  // WISP traffic, status output, or stdout metadata.
  const tlsMaterial = fs.readFileSync(TEST_CERTIFICATE_PATH);
  const tlsFailureMaterial = fs.readFileSync(TLS_FAILURE_CERTIFICATE_PATH);
  const context = {
    destinationRoutes: new Map(),
    cancelStreamPendingProofs: new Set(),
    cancelStreamPhase: "pre-cancel",
    cancelStreamSession: null,
    largeDownloadPhase: "pre-download",
    multiplexPending: new Map(),
    multiplexPhase: "pre-multiplex",
    nextCarrierId: 1,
    reconnectPhase: "pre-reconnect",
    reconnectDisconnectTimer: null,
    reconnectPendingRecovery: null,
    reconnectStreamSession: null,
    slowStreamPhase: "pre-stream",
    slowStreamResponse: null,
    slowStreamSession: null,
    slowStreamStageAckTimeout: null,
    slowStreamStageDelayMs: SLOW_STREAM_STAGE_DELAY_MS,
    slowStreamStageTimer: null,
    cspConnectSrcTargetPort: 0,
    cspConnectSrcTargetSockets: new Set(),
    echoPeers: new Set(),
    h1Port: 0,
    h2Port: 0,
    h2Sessions: new Set(),
    hostOrigin: options.hostOrigin,
    plaintextHttpControlDocumentServed: false,
    plaintextHttpControlPhase: "pre-control",
    plaintextHttpControlPort: 0,
    plaintextHttpControlSockets: new Set(),
    redirectCookieValue: crypto.randomBytes(16).toString("hex"),
    relays: new Set(),
    stats: {
      cacheConditionalRequests: 0,
      cacheNotModified304s: 0,
      cacheStore200s: 0,
      cacheUnexpectedRequests: 0,
      cancelStreamCancelResets: 0,
      cancelStreamFirstChunks: 0,
      cancelStreamProofs: 0,
      cancelStreamProofSessionMismatches: 0,
      cancelStreamProofTimeouts: 0,
      cancelStreamRequests: 0,
      cancelStreamUnexpectedResets: 0,
      largeDownloadBackpressureEvents: 0,
      largeDownloadBytes: 0,
      largeDownloadChunks: 0,
      largeDownloadCompletions: 0,
      largeDownloadRequests: 0,
      largeDownloadUnexpectedCloses: 0,
      localGateway443Requests: 0,
      localGateway443StreamsOpened: 0,
      localGatewayBlockedPortAttempts: 0,
      multiplexBarrierReleases: 0,
      multiplexBarrierTimeouts: 0,
      multiplexBothStreamsOpen: false,
      multiplexCorrelationFailures: 0,
      multiplexDistinctWispStreamCount: 0,
      multiplexH1Requests: 0,
      multiplexH2Requests: 0,
      multiplexResponses: 0,
      multiplexSharedCarrier: false,
      multiplexUnexpectedCloses: 0,
      slowStreamCompletedStreams: 0,
      slowStreamConsumerBurstBytes: 0,
      slowStreamConsumerBurstWrites: 0,
      slowStreamConsumerPauseReadyRequests: 0,
      slowStreamConsumerResumes: 0,
      slowStreamFirstStageAcks: 0,
      slowStreamFirstStages: 0,
      slowStreamSessionMismatches: 0,
      slowStreamStageAckTimeouts: 0,
      slowStreamProofs: 0,
      slowStreamRequests: 0,
      slowStreamSecondStageAcks: 0,
      slowStreamSecondStages: 0,
      slowStreamStageDelaySchedules: 0,
      slowStreamThirdStages: 0,
      slowStreamUnexpectedCloses: 0,
      corsRequests: 0,
      cspConnectSrcProofs: 0,
      cspConnectSrcTargetRequests: 0,
      cspConnectSrcTargetTcpConnections: 0,
      h2Requests: 0,
      mixedContentProofs: 0,
      mixedContentTargetPostControlRequests: 0,
      mixedContentTargetPostControlTcpConnections: 0,
      mixedContentTargetPostControlWispConnects: 0,
      plaintextHttpControlProofs: 0,
      plaintextHttpControlRequests: 0,
      plaintextHttpControlTcpConnections: 0,
      reconnectDisconnectRequests: 0,
      reconnectFirstChunkAcks: 0,
      reconnectFirstChunks: 0,
      reconnectRecoveryRequests: 0,
      reconnectSessionMismatches: 0,
      reconnectStreamRequests: 0,
      reconnectUnexpectedCloses: 0,
      reconnectUnexpectedRetries: 0,
      redirectCookieValidations: 0,
      redirectRequests: 0,
      rejectedDestinations: 0,
      relayErrors: 0,
      requestedDestinations: [],
      tlsMismatchHttpStreams: 0,
      tlsMismatchTcpConnections: 0,
      udpPackets: 0,
      webSocketEchoes: 0,
      wispSessions: 0,
    },
    tlsFailurePort: 0,
    tlsFailureSockets: new Set(),
    transcript: new Transcript(),
    wispTargetStreamsBySourcePort: new Map(),
    wispSockets: new Set(),
  };
  const h2Server = createH2Server(context, tlsMaterial);
  const h1Server = createH1Server(context, tlsMaterial);
  const cspConnectSrcTargetServer =
      createCspConnectSrcTargetServer(context, tlsMaterial);
  const plaintextHttpControlServer = createPlaintextHttpControlServer(context);
  const tlsFailureServer = createTlsFailureServer(context, tlsFailureMaterial);
  const wispServer = createWispServer(context);
  context.h2Port = await listenLoopback(h2Server);
  context.h1Port = await listenLoopback(h1Server);
  context.cspConnectSrcTargetPort =
      await listenLoopback(cspConnectSrcTargetServer);
  context.plaintextHttpControlPort =
      await listenLoopback(plaintextHttpControlServer);
  context.tlsFailurePort = await listenLoopback(tlsFailureServer);
  context.wispPort = await listenLoopback(wispServer);
  addDestinationRoute(
      context, TEST_HOSTNAME, context.h2Port, context.h2Port, "h2");
  addDestinationRoute(
      context, TEST_HOSTNAME, context.h1Port, context.h1Port, "h1");
  addDestinationRoute(
      context, TEST_HOSTNAME, context.cspConnectSrcTargetPort,
      context.cspConnectSrcTargetPort, "csp-connect-src");
  addDestinationRoute(
      context, TEST_HOSTNAME, context.plaintextHttpControlPort,
      context.plaintextHttpControlPort, "plaintext-control");
  addDestinationRoute(
      context, TEST_HOSTNAME, context.tlsFailurePort, context.tlsFailurePort,
      "tls-failure");
  addDestinationRoute(
      context, TEST_HOSTNAME, LOCAL_GATEWAY_HTTPS_PORT, context.h2Port,
      "local-gateway-443");
  context.transcript.add("fixture-ready", {
    cspConnectSrcTargetPort: context.cspConnectSrcTargetPort,
    h1Port: context.h1Port,
    h2Port: context.h2Port,
    plaintextHttpControlPort: context.plaintextHttpControlPort,
    tlsFailurePort: context.tlsFailurePort,
  });

  const metadata = {
    fixture: FIXTURE,
    mixedContentTargetUrl:
      "http://" + TEST_HOSTNAME + ":" + context.plaintextHttpControlPort +
      "/m5/mixed-content-target",
    plaintextHttpControlProofUrl:
      "http://" + TEST_HOSTNAME + ":" + context.plaintextHttpControlPort +
      "/m5/plaintext-control-proof",
    plaintextHttpControlUrl:
      "http://" + TEST_HOSTNAME + ":" + context.plaintextHttpControlPort +
      "/m5/plaintext-control",
    cspConnectSrcTargetUrl:
      `https://${TEST_HOSTNAME}:${context.cspConnectSrcTargetPort}/` +
      "m5/csp-connect-src-target",
    http1Url: `https://${TEST_HOSTNAME}:${context.h1Port}/m5/cors-resource`,
    httpsUrl: `https://${TEST_HOSTNAME}:${context.h2Port}/m5/`,
    protocol: 1,
    schema_version: 1,
    statusUrl: `http://${LOOPBACK_HOST}:${context.wispPort}${STATUS_PATH}`,
    redirectUrl:
      `https://${TEST_HOSTNAME}:${context.h2Port}/m5/redirect-cookie`,
    tlsFailureUrl:
      `https://${TEST_HOSTNAME}:${context.tlsFailurePort}/m5/tls-name-mismatch`,
    transcriptUrl: `http://${LOOPBACK_HOST}:${context.wispPort}${STATUS_PATH}`,
    webSocketUrl: `wss://${TEST_HOSTNAME}:${context.h1Port}/m5/ws`,
    wispEndpoint: `ws://${LOOPBACK_HOST}:${context.wispPort}${WISP_PATH}`,
  };

  let shuttingDown = false;
  const shutdown = async (reason) => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    context.transcript.add("fixture-shutdown", {reason});
    for (const relay of [...context.relays]) {
      relay.peer.close(1001, "fixture-shutdown");
      relay.close();
      // An upgraded socket is not owned by http.Server.close(). Once the
      // bounded close frame has been queued, destroy its read side too so a
      // non-cooperating test client cannot hold fixture shutdown open.
      relay.peer.destroy();
    }
    for (const peer of [...context.echoPeers]) {
      peer.close(1001, "fixture-shutdown");
      peer.destroy();
    }
    for (const socket of context.wispSockets) {
      socket.destroy();
    }
    for (const socket of context.tlsFailureSockets) {
      socket.destroy();
    }
    for (const socket of context.cspConnectSrcTargetSockets) {
      socket.destroy();
    }
    for (const socket of context.plaintextHttpControlSockets) {
      socket.destroy();
    }
    for (const pending of context.cancelStreamPendingProofs) {
      clearTimeout(pending.timeout);
    }
    context.cancelStreamPendingProofs.clear();
    clearSlowStreamStageTimer(context);
    clearSlowStreamStageAckTimeout(context);
    discardMultiplexPending(context);
    clearReconnectTimers(context);
    clearPendingReconnectRecovery(context);
    for (const session of context.h2Sessions) {
      session.close();
      // A headless outer browser can retain an idle H2 session after its Wasm
      // module exits. This is a loopback test origin, so terminate that
      // already-GOAWAYed session rather than letting server.close() hang.
      session.destroy();
    }
    h1Server.closeAllConnections?.();
    cspConnectSrcTargetServer.closeAllConnections?.();
    plaintextHttpControlServer.closeAllConnections?.();
    tlsFailureServer.closeAllConnections?.();
    wispServer.closeAllConnections?.();
    await Promise.all([
      closeServer(h2Server),
      closeServer(h1Server),
      closeServer(cspConnectSrcTargetServer),
      closeServer(plaintextHttpControlServer),
      closeServer(tlsFailureServer),
      closeServer(wispServer),
    ]);
    // This record is deliberately restricted to bounded metadata; in
    // particular it cannot contain certificate material, WebSocket payloads,
    // arbitrary request URLs, or caller-provided host strings.
    process.stdout.write(`${JSON.stringify(statusSummary(context, reason))}\n`,
        () => process.exit(0));
  };

  // This must be the first stdout line. A runner consumes it before opening
  // the outer host browser and passes only the loopback WISP endpoint into the
  // browser module configuration.
  process.stdout.write(`${JSON.stringify(metadata)}\n`);

  process.stdin.setEncoding("utf8");
  process.stdin.resume();
  process.stdin.on("data", (data) => {
    if (String(data).split(/\r?\n/).some((line) => line === "shutdown")) {
      void shutdown("stdin");
    }
  });
  // The browser runner intentionally inherits its own stdin rather than
  // keeping a pipe to this child. In CI that descriptor is commonly already
  // closed, which must not make the relay disappear immediately; only an
  // explicit command or a process signal requests shutdown.
  process.stdin.on("end", () => {});
  process.once("SIGTERM", () => void shutdown("sigterm"));
  process.once("SIGINT", () => void shutdown("sigint"));

  return {shutdown};
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  await start(options);
}

main().catch((error) => {
  // Startup errors occur before a usable metadata line exists. Keep details
  // on stderr so stdout remains a machine-readable relay protocol.
  process.stderr.write(`m5_wisp_test_server: ${error.message}\n`);
  process.exitCode = 2;
});

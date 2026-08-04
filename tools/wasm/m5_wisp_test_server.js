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
const RELAY_HANDSHAKE_TIMEOUT_MS = 10 * 1000;
const DESTINATION_IDLE_TIMEOUT_MS = 30 * 1000;

const REPOSITORY_ROOT = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)), "../..");
const TEST_CERTIFICATE_PATH = path.join(
    REPOSITORY_ROOT, "net/data/ssl/certificates/test_names.pem");

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
    const onError = (error) => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.off("error", onError);
      const address = server.address();
      if (!address || typeof address === "string" ||
          address.address !== LOOPBACK_HOST || !Number.isSafeInteger(address.port) ||
          address.port < 1 || address.port > 65535) {
        reject(new Error("test server did not bind an IPv4 loopback port"));
        return;
      }
      resolve(address.port);
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen({host: LOOPBACK_HOST, port: 0, exclusive: true});
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

function statusSnapshot(context) {
  return {
    fixture: FIXTURE,
    protocol: 1,
    ready: true,
    activeWispSessions: context.relays.size,
    corsRequests: context.stats.corsRequests,
    h2Requests: {
      count: context.stats.h2Requests,
      protocol: "h2",
    },
    rejectedDestinations: context.stats.rejectedDestinations,
    relayErrors: context.stats.relayErrors,
    requestedDestinations: context.stats.requestedDestinations.map(
        (destination) => ({...destination})),
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
    if (!hostname || !this.context.allowedPorts.has(port)) {
      this.context.stats.rejectedDestinations += 1;
      this._sendPacket(wispClosePacket(streamId, WISP_CLOSE_REASONS.BLOCKED));
      this.context.transcript.add("connect-rejected", {streamId, port});
      return;
    }

    const socket = net.connect({
      host: LOOPBACK_HOST,
      port,
      allowHalfOpen: false,
    });
    socket.setNoDelay(true);
    socket.setTimeout(DESTINATION_IDLE_TIMEOUT_MS);
    const stream = {
      id: streamId,
      port,
      socket,
      state: "connecting",
      closeSent: false,
      targetOutput: [],
      targetOutputBytes: 0,
      inboundBlocked: false,
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
      this.context.transcript.add("connect-open", {
        streamId,
        destination: `${TEST_HOSTNAME}:${port}`,
      });
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

function h2Page(context) {
  const h1CorsUrl = `https://${TEST_HOSTNAME}:${context.h1Port}/m5/cors-resource`;
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
  const h2ResourceURL = new URL("/m5/h2-resource", location.href).href;
  const corsURL = ${JSON.stringify(h1CorsUrl)};
  const socketURL = ${JSON.stringify(webSocketUrl)};
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      (value) => value.toString(16).padStart(2, "0")).join("");
  const state = {
    timerTicks: 0,
    h2Fetch: false,
    h2Protocol: "",
    altSvcH3Advertised: false,
    corsFetch: false,
    webSocketEcho: false,
    complete: false,
    failure: null,
  };
  const status = document.querySelector("#m5-status");
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

  // The Content Shell observer accepts its deterministic probe through a
  // string-valued JavaScript execution callback. Keep the network work async,
  // but serialize this synchronous snapshot so each periodic observer probe
  // can report the fixture's current state once it completes.
  window.__chromiumWasmM5Probe = () => JSON.stringify({
    protocol: 1,
    fixture,
    ready: state.complete && state.timerTicks >= 3,
    timerTicks: state.timerTicks,
    h2Fetch: state.h2Fetch,
    h2Protocol: state.h2Protocol,
    corsFetch: state.corsFetch,
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

      const corsResponse = await fetch(corsURL, {
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
      });
      state.corsFetch = corsResponse.ok &&
          await corsResponse.text() === "M5_CORS_OK";
      state.webSocketEcho = await echoNonce();
      state.complete = state.h2Fetch && state.altSvcH3Advertised &&
          state.corsFetch && state.webSocketEcho;
      status.textContent = state.complete ?
        "Chromium M5 TCP/H2/CORS/WebSocket checks passed." :
        "Chromium M5 network checks did not complete.";
    } catch (_) {
      state.failure = "network-check-failed";
      status.textContent = "Chromium M5 network checks failed.";
    }
  })();
})();
</script>`;
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
    if (requestPath === "/m5/") {
      const body = Buffer.from(h2Page(context));
      stream.respond(h2Headers({
        ":status": 200,
        "content-length": String(body.length),
        "content-type": "text/html; charset=utf-8",
        "content-security-policy":
          `default-src 'self'; connect-src 'self' https://${TEST_HOSTNAME}:${context.h1Port} wss://${TEST_HOSTNAME}:${context.h1Port}; base-uri 'none'; object-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'`,
      }));
      stream.end(body);
      context.transcript.add("h2-page");
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
    if (requestPath === "/m5/redirect") {
      stream.respond(h2Headers({":status": 302, location: "/m5/"}));
      stream.end();
      context.transcript.add("h2-redirect");
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

function createH1Server(context, tlsMaterial) {
  const server = https.createServer({cert: tlsMaterial, key: tlsMaterial},
      (request, response) => {
        const pageOrigin = `https://${TEST_HOSTNAME}:${context.h2Port}`;
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
  // This PEM contains the test server key as well as its certificate. It is
  // read only by the two loopback TLS listeners and is never serialized into
  // page content, WISP traffic, status output, or stdout metadata.
  const tlsMaterial = fs.readFileSync(TEST_CERTIFICATE_PATH);
  const context = {
    allowedPorts: new Set(),
    echoPeers: new Set(),
    h1Port: 0,
    h2Port: 0,
    h2Sessions: new Set(),
    hostOrigin: options.hostOrigin,
    relays: new Set(),
    stats: {
      corsRequests: 0,
      h2Requests: 0,
      rejectedDestinations: 0,
      relayErrors: 0,
      requestedDestinations: [],
      udpPackets: 0,
      webSocketEchoes: 0,
      wispSessions: 0,
    },
    transcript: new Transcript(),
    wispSockets: new Set(),
  };
  const h2Server = createH2Server(context, tlsMaterial);
  const h1Server = createH1Server(context, tlsMaterial);
  const wispServer = createWispServer(context);
  context.h2Port = await listenLoopback(h2Server);
  context.h1Port = await listenLoopback(h1Server);
  context.wispPort = await listenLoopback(wispServer);
  context.allowedPorts.add(context.h2Port);
  context.allowedPorts.add(context.h1Port);
  context.transcript.add("fixture-ready", {
    h1Port: context.h1Port,
    h2Port: context.h2Port,
  });

  const metadata = {
    fixture: FIXTURE,
    http1Url: `https://${TEST_HOSTNAME}:${context.h1Port}/m5/cors-resource`,
    httpsUrl: `https://${TEST_HOSTNAME}:${context.h2Port}/m5/`,
    protocol: 1,
    schema_version: 1,
    statusUrl: `http://${LOOPBACK_HOST}:${context.wispPort}${STATUS_PATH}`,
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
    for (const session of context.h2Sessions) {
      session.close();
      // A headless outer browser can retain an idle H2 session after its Wasm
      // module exits. This is a loopback test origin, so terminate that
      // already-GOAWAYed session rather than letting server.close() hang.
      session.destroy();
    }
    h1Server.closeAllConnections?.();
    wispServer.closeAllConnections?.();
    await Promise.all([
      closeServer(h2Server),
      closeServer(h1Server),
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

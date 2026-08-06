#!/usr/bin/env node
// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

"use strict";

// A deliberately constrained WISP v2.1 gateway for the opt-in M5 public
// HTTPS lane.  This is intentionally separate from m5_wisp_test_server.js:
// that file is a controlled fixture with logical local routes, while this
// gateway is suitable for an operator to put behind an independently managed
// public WSS terminator/forwarder.
//
// The gateway itself always binds IPv4 loopback.  Its runtime configuration
// remains outside the checkout and contains only an allowlist of public DNS
// hostnames.  The public TLS endpoint terminates before this loopback-only
// HTTP Upgrade listener.  It never exposes an HTTP status
// endpoint, destination transcript, or target-bearing diagnostic output.
// Chromium's TLS and HTTP stacks remain above the raw node:net TCP sockets.

import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import {fileURLToPath, pathToFileURL} from "node:url";
import {TextDecoder} from "node:util";

export const LOOPBACK_HOST = "127.0.0.1";
export const WISP_PATH = "/wisp/";
export const WISP_PROTOCOL = "wisp";
export const WISP_V21_STREAM_OPEN_CONFIRMATION_EXTENSION = 0x05;

export const WISP_PACKET_TYPES = Object.freeze({
  CONNECT: 0x01,
  DATA: 0x02,
  CONTINUE: 0x03,
  CLOSE: 0x04,
  INFO: 0x05,
});

export const WISP_CLOSE_REASONS = Object.freeze({
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

const CONFIG_SCHEMA_VERSION = 1;
const MAX_CONFIG_BYTES = 32 * 1024;
const MAX_HOSTNAME_BYTES = 253;
const MAX_ALLOWED_HOSTS = 64;
const MAX_WEBSOCKET_CONTROL_BYTES = 125;
const DEFAULT_LIMITS = Object.freeze({
  connectTimeoutMs: 15 * 1000,
  handshakeTimeoutMs: 15 * 1000,
  idleTimeoutMs: 120 * 1000,
  maxDataPayloadBytes: 16 * 1024,
  maxSessions: 8,
  maxSessionQueueBytes: 512 * 1024,
  maxStreamsPerSession: 32,
  maxStreamQueueBytes: 128 * 1024,
  maxWebSocketBufferedBytes: 512 * 1024,
  streamPacketCredit: 64,
  globalPacketCredit: 1024,
});

const CONFIG_FIELDS = new Set([
  "approved_hosts",
  "limits",
  "listen_port",
  "schema_version",
]);
const LIMIT_FIELDS = new Set([
  "connect_timeout_ms",
  "global_packet_credit",
  "handshake_timeout_ms",
  "idle_timeout_ms",
  "max_data_payload_bytes",
  "max_sessions",
  "max_session_queue_bytes",
  "max_stream_queue_bytes",
  "max_streams_per_session",
  "max_websocket_buffer_bytes",
  "stream_packet_credit",
]);
const PUBLIC_SPECIAL_USE_HOSTNAME_SUFFIXES = Object.freeze([
  ".home.arpa",
  ".invalid",
  ".local",
  ".localhost",
  ".onion",
  ".test",
]);
const REPOSITORY_ROOT = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)), "../..");
const VALIDATED_CONFIGS = new WeakSet();

function fail(message) {
  throw new Error(message);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" &&
      Object.getPrototypeOf(value) === Object.prototype;
}

function hasOnlyFields(value, allowedFields) {
  return Object.keys(value).every((field) => allowedFields.has(field));
}

function boundedInteger(value, name, minimum, maximum, fallback) {
  if (value === undefined) {
    return fallback;
  }
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(`invalid public WISP gateway ${name}`);
  }
  return value;
}

function isOutsideRepository(configPath) {
  const relative = path.relative(REPOSITORY_ROOT, configPath);
  return relative === ".." || relative.startsWith(`..${path.sep}`) ||
      path.isAbsolute(relative);
}

// This deliberately mirrors the public-DNS restriction used by the M5 runner.
// A destination is always passed to node:net as a hostname, never as a URL,
// literal address, proxy target, or host:port authority.
export function normalizePublicDnsHostname(value) {
  if (typeof value !== "string" || value.length === 0 ||
      value.length > MAX_HOSTNAME_BYTES || !/^[\x00-\x7f]+$/.test(value)) {
    return null;
  }
  const normalized = value.toLowerCase();
  if (normalized === "localhost" || normalized === "home.arpa" ||
      normalized.endsWith(".") ||
      PUBLIC_SPECIAL_USE_HOSTNAME_SUFFIXES.some((suffix) =>
        normalized.endsWith(suffix)) ||
      normalized.includes("..") || net.isIP(normalized) !== 0 ||
      !normalized.includes(".")) {
    return null;
  }
  const labels = normalized.split(".");
  if (!labels.every((label) => label.length > 0 && label.length <= 63 &&
      /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label))) {
    return null;
  }
  // Reject legacy numeric IPv4 forms before Node's resolver can reinterpret a
  // hostname-like string as a literal destination.
  const isLegacyIpv4Component = (label) =>
    (/^0x[0-9a-f]+$/.test(label) || /^[0-9]+$/.test(label));
  if (labels.length <= 4 && labels.every(isLegacyIpv4Component)) {
    return null;
  }
  return normalized;
}

function parseLimits(raw) {
  if (raw === undefined) {
    return {...DEFAULT_LIMITS};
  }
  if (!isPlainObject(raw) || !hasOnlyFields(raw, LIMIT_FIELDS)) {
    fail("invalid public WISP gateway limits");
  }
  const limits = {
    connectTimeoutMs: boundedInteger(raw.connect_timeout_ms,
        "connect timeout", 1000, 120 * 1000, DEFAULT_LIMITS.connectTimeoutMs),
    globalPacketCredit: boundedInteger(raw.global_packet_credit,
        "global packet credit", 1, 65535, DEFAULT_LIMITS.globalPacketCredit),
    handshakeTimeoutMs: boundedInteger(raw.handshake_timeout_ms,
        "handshake timeout", 1000, 120 * 1000,
        DEFAULT_LIMITS.handshakeTimeoutMs),
    idleTimeoutMs: boundedInteger(raw.idle_timeout_ms,
        "idle timeout", 1000, 15 * 60 * 1000, DEFAULT_LIMITS.idleTimeoutMs),
    maxDataPayloadBytes: boundedInteger(raw.max_data_payload_bytes,
        "data payload limit", 1, 64 * 1024,
        DEFAULT_LIMITS.maxDataPayloadBytes),
    maxSessions: boundedInteger(raw.max_sessions,
        "session limit", 1, 64, DEFAULT_LIMITS.maxSessions),
    maxSessionQueueBytes: boundedInteger(raw.max_session_queue_bytes,
        "session queue limit", 4096, 16 * 1024 * 1024,
        DEFAULT_LIMITS.maxSessionQueueBytes),
    maxStreamQueueBytes: boundedInteger(raw.max_stream_queue_bytes,
        "stream queue limit", 1024, 8 * 1024 * 1024,
        DEFAULT_LIMITS.maxStreamQueueBytes),
    maxStreamsPerSession: boundedInteger(raw.max_streams_per_session,
        "stream limit", 1, 256, DEFAULT_LIMITS.maxStreamsPerSession),
    maxWebSocketBufferedBytes: boundedInteger(raw.max_websocket_buffer_bytes,
        "WebSocket queue limit", 4096, 16 * 1024 * 1024,
        DEFAULT_LIMITS.maxWebSocketBufferedBytes),
    streamPacketCredit: boundedInteger(raw.stream_packet_credit,
        "stream packet credit", 1, 65535, DEFAULT_LIMITS.streamPacketCredit),
  };
  if (limits.maxSessionQueueBytes < limits.maxStreamQueueBytes ||
      limits.maxWebSocketBufferedBytes < limits.maxDataPayloadBytes + 5) {
    fail("incompatible public WISP gateway limits");
  }
  return limits;
}

export function validatePublicWispGatewayConfig(raw) {
  if (!isPlainObject(raw) || !hasOnlyFields(raw, CONFIG_FIELDS) ||
      raw.schema_version !== CONFIG_SCHEMA_VERSION ||
      !Array.isArray(raw.approved_hosts) ||
      raw.approved_hosts.length === 0 ||
      raw.approved_hosts.length > MAX_ALLOWED_HOSTS) {
    fail("invalid public WISP gateway configuration");
  }
  const approvedHosts = [];
  const seenApprovedHosts = new Set();
  for (const hostname of raw.approved_hosts) {
    const normalized = normalizePublicDnsHostname(hostname);
    if (!normalized || seenApprovedHosts.has(normalized)) {
      fail("invalid public WISP gateway approved hosts");
    }
    seenApprovedHosts.add(normalized);
    approvedHosts.push(normalized);
  }
  const listenPort = boundedInteger(raw.listen_port, "listen port", 0, 65535,
                                    0);
  const limits = parseLimits(raw.limits);
  const config = Object.freeze({
    approvedHosts: Object.freeze(approvedHosts),
    listenPort,
    limits: Object.freeze(limits),
  });
  VALIDATED_CONFIGS.add(config);
  return config;
}

export function loadExternalPublicWispGatewayConfig(configPath) {
  if (typeof configPath !== "string" || configPath.length === 0 ||
      configPath.length > 4096) {
    fail("public WISP gateway configuration path is invalid");
  }
  let resolved;
  try {
    resolved = fs.realpathSync(configPath);
  } catch (_) {
    fail("public WISP gateway configuration could not be read");
  }
  if (!isOutsideRepository(resolved)) {
    fail("public WISP gateway configuration must remain outside the repository");
  }
  let bytes;
  try {
    bytes = fs.readFileSync(resolved);
  } catch (_) {
    fail("public WISP gateway configuration could not be read");
  }
  if (bytes.length === 0 || bytes.length > MAX_CONFIG_BYTES) {
    fail("public WISP gateway configuration is invalid");
  }
  let raw;
  try {
    raw = JSON.parse(bytes.toString("utf8"));
  } catch (_) {
    fail("public WISP gateway configuration is invalid");
  }
  return validatePublicWispGatewayConfig(raw);
}

function websocketAcceptValue(key) {
  return crypto.createHash("sha1")
      .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
      .digest("base64");
}

function isValidWebSocketKey(key) {
  if (typeof key !== "string" || !/^[A-Za-z0-9+/]{22}==$/.test(key)) {
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

// The Origin header is an RFC 6454 serialization, not a URL accepted for
// navigation.  Require its literal loopback form and a nonzero explicit port.
function isAllowedLoopbackOrigin(value) {
  if (typeof value !== "string") {
    return false;
  }
  const match = /^http:\/\/127\.0\.0\.1:([1-9][0-9]{0,4})$/.exec(value);
  return match !== null && Number(match[1]) <= 65535;
}

function websocketFrame(opcode, payload) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  let header;
  if (body.length <= 125) {
    header = Buffer.from([0x80 | opcode, body.length]);
  } else if (body.length <= 0xffff) {
    header = Buffer.allocUnsafe(4);
    header[0] = 0x80 | opcode;
    header[1] = 126;
    header.writeUInt16BE(body.length, 2);
  } else {
    header = Buffer.allocUnsafe(10);
    header[0] = 0x80 | opcode;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(body.length), 2);
  }
  return Buffer.concat([header, body]);
}

function websocketClosePayload(code, reason) {
  const reasonBytes = Buffer.from(reason, "utf8").subarray(0, 123);
  const result = Buffer.allocUnsafe(2 + reasonBytes.length);
  result.writeUInt16BE(code, 0);
  reasonBytes.copy(result, 2);
  return result;
}

function wispPacket(type, streamId, payload = Buffer.alloc(0)) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  const packet = Buffer.allocUnsafe(5 + body.length);
  packet[0] = type;
  packet.writeUInt32LE(streamId, 1);
  body.copy(packet, 5);
  return packet;
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
  // WISP v2.1 with the required zero-length stream-open-confirmation
  // extension.  The Chromium bridge rejects v1 or an unconfirmed stream.
  return wispPacket(WISP_PACKET_TYPES.INFO, 0, Buffer.from([
    2, 1,
    WISP_V21_STREAM_OPEN_CONFIRMATION_EXTENSION, 0, 0, 0, 0,
  ]));
}

function maximumInboundWispPacketBytes(limits) {
  // CONNECT needs a transport byte, a little-endian port, and a complete
  // hostname even when a deliberately small DATA limit is configured.
  return Math.max(limits.maxDataPayloadBytes + 5, MAX_HOSTNAME_BYTES + 8);
}

function maximumOutboundWispPacketBytes(limits) {
  // INFO is a 12-byte WISP packet and is sent before a stream exists.
  return Math.max(limits.maxDataPayloadBytes + 5, serverInfoPacket().length);
}

function isExpectedClientInfo(payload) {
  return payload.length === 7 && payload[0] === 2 && payload[1] === 1 &&
      payload[2] === WISP_V21_STREAM_OPEN_CONFIRMATION_EXTENSION &&
      payload.readUInt32LE(3) === 0;
}

// A bounded RFC 6455 peer.  The gateway accepts binary messages only; every
// client frame must be masked.  The only WISP data unit that reaches a session
// is a complete, size-bounded binary message.
class WebSocketPeer {
  constructor(socket, limits, callbacks) {
    this.socket = socket;
    this.limits = limits;
    this.callbacks = callbacks;
    this.backpressured = false;
    this.closeNotified = false;
    this.closeSent = false;
    this.closed = false;
    this.fragmentBytes = 0;
    this.fragmentOpcode = null;
    this.fragments = [];
    this.input = Buffer.alloc(0);
    this.inputPaused = false;
    this.maximumInboundPacketBytes = maximumInboundWispPacketBytes(limits);
    this.maximumOutboundPacketBytes = maximumOutboundWispPacketBytes(limits);

    socket.on("data", (chunk) => this._receive(chunk));
    socket.on("drain", () => {
      this.backpressured = false;
      this.callbacks.onWritable();
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

  sendBinary(payload) {
    if (this.closed || this.backpressured ||
        payload.length > this.maximumOutboundPacketBytes) {
      return {accepted: false, blocked: true};
    }
    const frame = websocketFrame(0x02, payload);
    if (this.socket.writableLength + frame.length >
        this.limits.maxWebSocketBufferedBytes) {
      this.backpressured = true;
      return {accepted: false, blocked: true};
    }
    const writable = this.socket.write(frame);
    if (!writable) {
      this.backpressured = true;
    }
    return {accepted: true, blocked: !writable};
  }

  close(code = 1000, reason = "") {
    if (this.closed) {
      return;
    }
    if (!this.closeSent && this.socket.writable) {
      this.closeSent = true;
      try {
        this.socket.write(websocketFrame(
            0x08, websocketClosePayload(code, reason)));
      } catch (_) {
        // Destroy below if a terminal socket rejects the close frame.
      }
    }
    this.closed = true;
    this.socket.end();
    this._notifyClosed();
  }

  destroy() {
    this.closed = true;
    this.socket.destroy();
    this._notifyClosed();
  }

  _receive(chunk) {
    if (this.closed || !Buffer.isBuffer(chunk) ||
        this.input.length + chunk.length >
            this.limits.maxWebSocketBufferedBytes + 14) {
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
      const opcode = first & 0x0f;
      const masked = (second & 0x80) !== 0;
      let payloadLength = second & 0x7f;
      let offset = 2;
      if ((first & 0x70) !== 0 || !masked) {
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
        if (length > BigInt(this.maximumInboundPacketBytes)) {
          this.close(1009, "frame-too-large");
          return;
        }
        payloadLength = Number(length);
        offset += 8;
      }
      if (payloadLength > this.maximumInboundPacketBytes) {
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
        if (!fin || payloadLength > MAX_WEBSOCKET_CONTROL_BYTES) {
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
            this.socket.write(websocketFrame(0x08, payload));
          }
          this.closed = true;
          this.socket.end();
          this._notifyClosed();
          return;
        }
        if (opcode === 0x09) {
          const result = this._sendControl(0x0a, payload);
          if (!result) {
            return;
          }
          continue;
        }
        if (opcode === 0x0a) {
          continue;
        }
        this.close(1002, "unknown-control");
        return;
      }

      if (opcode === 0x00) {
        if (this.fragmentOpcode === null ||
            !this._appendFragment(payload, this.maximumInboundPacketBytes)) {
          this.close(1002, "invalid-fragment");
          return;
        }
        if (fin) {
          const message = Buffer.concat(this.fragments, this.fragmentBytes);
          this.fragmentOpcode = null;
          this.fragments = [];
          this.fragmentBytes = 0;
          this._deliverMessage(message);
        }
        continue;
      }
      if (opcode !== 0x02 || this.fragmentOpcode !== null) {
        this.close(1003, "binary-required");
        return;
      }
      if (fin) {
        this._deliverMessage(payload);
        continue;
      }
      this.fragmentOpcode = opcode;
      this.fragments = [];
      this.fragmentBytes = 0;
      if (!this._appendFragment(payload, this.maximumInboundPacketBytes)) {
        this.close(1009, "message-too-large");
        return;
      }
    }
  }

  _appendFragment(payload, maximum) {
    if (this.fragmentBytes + payload.length > maximum) {
      return false;
    }
    this.fragments.push(payload);
    this.fragmentBytes += payload.length;
    return true;
  }

  _deliverMessage(payload) {
    if (payload.length < 5 || payload.length > this.maximumInboundPacketBytes) {
      this.close(1002, "invalid-wisp-message");
      return;
    }
    try {
      this.callbacks.onMessage(payload);
    } catch (_) {
      this.close(1011, "handler-failure");
    }
  }

  _sendControl(opcode, payload) {
    if (this.closed || this.socket.writableLength + payload.length + 2 >
        this.limits.maxWebSocketBufferedBytes) {
      this.close(1009, "output-limit");
      return false;
    }
    if (!this.socket.write(websocketFrame(opcode, payload))) {
      this.backpressured = true;
    }
    return true;
  }

  _notifyClosed() {
    if (this.closeNotified) {
      return;
    }
    this.closeNotified = true;
    this.callbacks.onClosed();
  }
}

class WispSession {
  constructor(peer, gateway) {
    this.peer = peer;
    this.gateway = gateway;
    this.config = gateway.config;
    this.limits = this.config.limits;
    this.closed = false;
    this.phase = "awaiting-info";
    this.queuedToClientBytes = 0;
    this.queuedToTargetBytes = 0;
    this.streams = new Map();
    this.handshakeTimer = setTimeout(() => {
      if (this.phase !== "ready") {
        this.protocolFailure();
      }
    }, this.limits.handshakeTimeoutMs);
    this.handshakeTimer.unref?.();
    this.idleTimer = null;
    this._touch();
    this._send(serverInfoPacket());
  }

  receive(packet) {
    if (this.closed || packet.length < 5) {
      return;
    }
    this._touch();
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
      case WISP_PACKET_TYPES.CONTINUE:
        // Chromium's bridge currently consumes server-side credit only.  A
        // syntactically valid client CONTINUE has no unsafe side effect.
        if (payload.length !== 4) {
          this.protocolFailure();
        }
        break;
      default:
        this.protocolFailure();
        break;
    }
  }

  writable() {
    if (this.closed) {
      return;
    }
    for (const stream of this.streams.values()) {
      this._flushPendingContinue(stream);
      this._flushClientOutput(stream);
    }
    this._resumePeerInputIfPossible();
  }

  peerClosed() {
    this.close();
  }

  close() {
    if (this.closed) {
      return;
    }
    this.closed = true;
    clearTimeout(this.handshakeTimer);
    clearTimeout(this.idleTimer);
    for (const stream of [...this.streams.values()]) {
      this._removeStream(stream, {destroy: true, sendClose: false});
    }
    this.gateway.sessions.delete(this);
  }

  protocolFailure() {
    if (this.closed) {
      return;
    }
    this._send(wispClosePacket(
        0, WISP_CLOSE_REASONS.INCOMPATIBLE_EXTENSIONS));
    this.peer.close(1002, "wisp-protocol-error");
    this.close();
  }

  _touch() {
    clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      if (!this.closed) {
        this.peer.close(1001, "idle-timeout");
        this.close();
      }
    }, this.limits.idleTimeoutMs);
    this.idleTimer.unref?.();
  }

  _receiveInfo(streamId, payload) {
    if (this.phase !== "awaiting-info" || streamId !== 0 ||
        !isExpectedClientInfo(payload)) {
      this.protocolFailure();
      return;
    }
    this.phase = "ready";
    clearTimeout(this.handshakeTimer);
    this._send(wispContinuePacket(0, this.limits.globalPacketCredit));
  }

  _receiveConnect(streamId, payload) {
    if (this.phase !== "ready") {
      this.protocolFailure();
      return;
    }
    if (streamId === 0 || this.streams.has(streamId)) {
      this._send(wispClosePacket(streamId, WISP_CLOSE_REASONS.INVALID_STREAM));
      return;
    }
    const destination = this._parseDestination(payload);
    // The target gate is intentionally before net.connect.  This makes same
    // host :444, every other port, UDP, malformed names, and unapproved names
    // a native Chromium ERR_BLOCKED_BY_ADMINISTRATOR through the WISP BLOCKED
    // close rather than an attempted connection or a misleading refusal.
    if (!destination || destination.port !== 443 ||
        !this.gateway.approvedHosts.has(destination.hostname) ||
        this.streams.size >= this.limits.maxStreamsPerSession) {
      this._send(wispClosePacket(streamId, WISP_CLOSE_REASONS.BLOCKED));
      return;
    }
    let socket;
    try {
      socket = this.gateway.connectTarget(destination.hostname, 443);
    } catch (_) {
      this._send(wispClosePacket(streamId, WISP_CLOSE_REASONS.REFUSED));
      return;
    }
    if (!socket || typeof socket.on !== "function" ||
        typeof socket.write !== "function") {
      this._send(wispClosePacket(streamId, WISP_CLOSE_REASONS.REFUSED));
      return;
    }
    const stream = {
      awaitingTargetDrain: false,
      closeAfterOutput: null,
      closeSent: false,
      connectTimer: null,
      continueBlocked: false,
      continuePending: false,
      id: streamId,
      socket,
      state: "connecting",
      targetBlocked: false,
      targetClosed: false,
      toClient: [],
      toClientBytes: 0,
      toTarget: [],
      toTargetBytes: 0,
    };
    this.streams.set(streamId, stream);
    try {
      socket.setNoDelay(true);
      socket.setTimeout(this.limits.idleTimeoutMs);
      socket.on("connect", () => this._targetConnected(stream));
      socket.on("data", (bytes) => this._targetData(stream, bytes));
      socket.on("drain", () => this._targetDrained(stream));
      socket.on("timeout", () => this._targetTerminated(
          stream, WISP_CLOSE_REASONS.STREAM_TIMED_OUT));
      socket.on("end", () => this._targetTerminated(
          stream, WISP_CLOSE_REASONS.VOLUNTARY));
      socket.on("error", () => this._targetTerminated(stream,
          stream.state === "connecting" ? WISP_CLOSE_REASONS.REFUSED :
            WISP_CLOSE_REASONS.NETWORK_ERROR));
      socket.on("close", () => {
        if (!stream.targetClosed) {
          this._targetTerminated(stream, WISP_CLOSE_REASONS.NETWORK_ERROR);
        }
      });
      stream.connectTimer = setTimeout(() => {
        if (this.streams.get(stream.id) === stream &&
            stream.state === "connecting") {
          this._targetTerminated(stream, WISP_CLOSE_REASONS.STREAM_TIMED_OUT);
        }
      }, this.limits.connectTimeoutMs);
      stream.connectTimer.unref?.();
    } catch (_) {
      this._removeStream(stream, {destroy: true, sendClose: false});
      this._send(wispClosePacket(streamId, WISP_CLOSE_REASONS.REFUSED));
    }
  }

  _parseDestination(payload) {
    if (payload.length < 4 || payload[0] !== 0x01) {  // TCP only.
      return null;
    }
    const port = payload.readUInt16LE(1);
    let hostname;
    try {
      hostname = new TextDecoder("utf-8", {fatal: true}).decode(
          payload.subarray(3));
    } catch (_) {
      return null;
    }
    const normalized = normalizePublicDnsHostname(hostname);
    return normalized ? {hostname: normalized, port} : null;
  }

  _targetConnected(stream) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        stream.state !== "connecting") {
      stream.socket.destroy();
      return;
    }
    clearTimeout(stream.connectTimer);
    stream.connectTimer = null;
    stream.state = "open";
    this._touch();
    stream.continuePending = true;
    this._flushPendingContinue(stream);
    this._flushTargetInput(stream);
  }

  _receiveData(streamId, payload) {
    if (this.phase !== "ready" || streamId === 0) {
      this.protocolFailure();
      return;
    }
    const stream = this.streams.get(streamId);
    if (!stream || stream.state !== "open" ||
        payload.length === 0 || payload.length > this.limits.maxDataPayloadBytes) {
      if (stream) {
        this._targetTerminated(stream, WISP_CLOSE_REASONS.THROTTLED);
      } else {
        this._send(wispClosePacket(streamId, WISP_CLOSE_REASONS.INVALID_STREAM));
      }
      return;
    }
    const copy = Buffer.from(payload);
    if (stream.toTargetBytes + copy.length > this.limits.maxStreamQueueBytes ||
        this.queuedToTargetBytes + copy.length > this.limits.maxSessionQueueBytes) {
      this._targetTerminated(stream, WISP_CLOSE_REASONS.THROTTLED);
      return;
    }
    stream.toTarget.push(copy);
    stream.toTargetBytes += copy.length;
    this.queuedToTargetBytes += copy.length;
    this._flushTargetInput(stream);
  }

  _receiveClose(streamId, payload) {
    if (this.phase !== "ready" || payload.length !== 1) {
      this.protocolFailure();
      return;
    }
    if (streamId === 0) {
      this.peer.close(1000, "client-close");
      this.close();
      return;
    }
    const stream = this.streams.get(streamId);
    if (stream) {
      this._removeStream(stream, {destroy: true, sendClose: false});
    }
  }

  _flushTargetInput(stream) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        stream.state !== "open" || stream.targetClosed) {
      return;
    }
    while (stream.toTarget.length > 0) {
      const chunk = stream.toTarget[0];
      if (stream.socket.writableLength + chunk.length >
          this.limits.maxStreamQueueBytes) {
        stream.targetBlocked = true;
        this.peer.pauseInput();
        return;
      }
      const writable = stream.socket.write(chunk);
      stream.toTarget.shift();
      stream.toTargetBytes -= chunk.length;
      this.queuedToTargetBytes -= chunk.length;
      if (!writable) {
        stream.awaitingTargetDrain = true;
        stream.targetBlocked = true;
        this.peer.pauseInput();
        return;
      }
      this._targetInputForwarded(stream);
    }
    stream.targetBlocked = false;
    this._resumePeerInputIfPossible();
  }

  _targetDrained(stream) {
    if (this.closed || this.streams.get(stream.id) !== stream) {
      return;
    }
    if (stream.awaitingTargetDrain) {
      stream.awaitingTargetDrain = false;
      this._targetInputForwarded(stream);
    }
    stream.targetBlocked = false;
    this._flushTargetInput(stream);
    this._resumePeerInputIfPossible();
  }

  _targetData(stream, bytes) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        stream.state !== "open" || stream.targetClosed || !Buffer.isBuffer(bytes)) {
      return;
    }
    this._touch();
    for (let offset = 0; offset < bytes.length;
         offset += this.limits.maxDataPayloadBytes) {
      const chunk = Buffer.from(bytes.subarray(
          offset, Math.min(offset + this.limits.maxDataPayloadBytes,
                           bytes.length)));
      if (stream.toClientBytes + chunk.length > this.limits.maxStreamQueueBytes ||
          this.queuedToClientBytes + chunk.length > this.limits.maxSessionQueueBytes) {
        this._targetTerminated(stream, WISP_CLOSE_REASONS.THROTTLED);
        return;
      }
      stream.toClient.push(chunk);
      stream.toClientBytes += chunk.length;
      this.queuedToClientBytes += chunk.length;
    }
    this._flushClientOutput(stream);
  }

  _targetInputForwarded(stream) {
    // WISP CONTINUE advertises an absolute remaining packet credit.  The
    // Chromium bridge decrements it per outgoing DATA packet, so grant fresh
    // credit only after that packet has entered the raw TCP writer (or its
    // writer drain callback), never merely when it arrived from WebSocket.
    stream.continuePending = true;
    this._flushPendingContinue(stream);
  }

  _flushPendingContinue(stream) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        !stream.continuePending) {
      return;
    }
    const result = this._send(wispContinuePacket(
        stream.id, this.limits.streamPacketCredit));
    if (!result.accepted) {
      stream.continueBlocked = true;
      this.peer.pauseInput();
      return;
    }
    stream.continuePending = false;
    stream.continueBlocked = false;
    if (result.blocked) {
      this.peer.pauseInput();
    }
  }

  _flushClientOutput(stream) {
    if (this.closed || this.streams.get(stream.id) !== stream) {
      return;
    }
    while (stream.toClient.length > 0) {
      const chunk = stream.toClient[0];
      const result = this._send(wispPacket(WISP_PACKET_TYPES.DATA,
          stream.id, chunk));
      if (!result.accepted) {
        stream.socket.pause();
        return;
      }
      stream.toClient.shift();
      stream.toClientBytes -= chunk.length;
      this.queuedToClientBytes -= chunk.length;
      if (result.blocked) {
        stream.socket.pause();
        return;
      }
    }
    if (!stream.targetClosed) {
      stream.socket.resume();
    }
    if (stream.closeAfterOutput !== null) {
      this._removeStream(stream, {
        destroy: true,
        sendClose: true,
        reason: stream.closeAfterOutput,
      });
    }
  }

  _targetTerminated(stream, reason) {
    if (this.closed || this.streams.get(stream.id) !== stream ||
        stream.targetClosed) {
      return;
    }
    stream.targetClosed = true;
    clearTimeout(stream.connectTimer);
    stream.connectTimer = null;
    stream.closeAfterOutput = reason;
    if (stream.toClient.length === 0) {
      this._removeStream(stream, {destroy: true, sendClose: true, reason});
      return;
    }
    this._flushClientOutput(stream);
  }

  _removeStream(stream, options) {
    if (this.streams.get(stream.id) !== stream) {
      return;
    }
    this.streams.delete(stream.id);
    clearTimeout(stream.connectTimer);
    stream.connectTimer = null;
    this.queuedToClientBytes = Math.max(
        0, this.queuedToClientBytes - stream.toClientBytes);
    this.queuedToTargetBytes = Math.max(
        0, this.queuedToTargetBytes - stream.toTargetBytes);
    stream.toClient = [];
    stream.toTarget = [];
    stream.toClientBytes = 0;
    stream.toTargetBytes = 0;
    stream.targetClosed = true;
    if (options.sendClose && !stream.closeSent) {
      stream.closeSent = true;
      this._send(wispClosePacket(stream.id, options.reason));
    }
    if (options.destroy && !stream.socket.destroyed) {
      stream.socket.destroy();
    }
    this._resumePeerInputIfPossible();
  }

  _resumePeerInputIfPossible() {
    if (![...this.streams.values()].some((stream) =>
      stream.targetBlocked || stream.continueBlocked)) {
      this.peer.resumeInput();
    }
  }

  _send(packet) {
    if (this.closed) {
      return {accepted: false, blocked: true};
    }
    const result = this.peer.sendBinary(packet);
    if (!result.accepted && this.peer.closed) {
      this.close();
    }
    return result;
  }
}

function rejectUpgrade(socket, status) {
  if (!socket.destroyed) {
    socket.write(`HTTP/1.1 ${status}\r\nConnection: close\r\n` +
        "Content-Length: 0\r\n\r\n");
    socket.destroy();
  }
}

function isValidUpgrade(request) {
  return request.method === "GET" && request.httpVersion === "1.1" &&
      request.url === WISP_PATH &&
      headerContainsToken(request.headers.connection, "upgrade") &&
      String(request.headers.upgrade || "").toLowerCase() === "websocket" &&
      request.headers["sec-websocket-version"] === "13" &&
      isValidWebSocketKey(request.headers["sec-websocket-key"]) &&
      isAllowedLoopbackOrigin(request.headers.origin);
}

function validTestingHooks(hooks) {
  if (hooks === undefined) {
    return Object.freeze({});
  }
  if (process.env.NODE_ENV !== "test" || !isPlainObject(hooks) ||
      !hasOnlyFields(hooks, new Set(["connectForTesting"])) ||
      typeof hooks.connectForTesting !== "function") {
    fail("public WISP gateway test hooks are unavailable");
  }
  // The hook is deliberately unavailable to the CLI. It exists only so a
  // wire test can map a logically approved :443 route to an ephemeral local
  // raw TCP listener without reserving a privileged port on the test host.
  return Object.freeze({connectForTesting: hooks.connectForTesting});
}

export class PublicWispGateway {
  constructor(config, hooks = undefined) {
    this.config = VALIDATED_CONFIGS.has(config) ? config :
        validatePublicWispGatewayConfig(config);
    this.approvedHosts = new Set(this.config.approvedHosts);
    this.hooks = validTestingHooks(hooks);
    this.server = null;
    this.sockets = new Set();
    this.sessions = new Set();
  }

  connectTarget(hostname, port) {
    if (this.hooks.connectForTesting) {
      return this.hooks.connectForTesting(hostname, port);
    }
    // Do not replace this with fetch(), http(s).request(), a CONNECT proxy, or
    // another host-network API.  Chromium owns TLS and HTTP over this raw TCP
    // stream, and the allowlist gate in WispSession runs before this call.
    return net.connect({allowHalfOpen: false, host: hostname, port});
  }

  async start() {
    if (this.server) {
      fail("public WISP gateway is already started");
    }
    const server = http.createServer((_request, response) => {
      // No HTTP API, diagnostics, or target-bearing status is served here.
      response.writeHead(404, {
        "Cache-Control": "no-store",
        "Connection": "close",
        "Content-Length": "0",
        "X-Content-Type-Options": "nosniff",
      });
      response.end();
    });
    // A WISP carrier owns one TCP connection for its entire lifetime. Bound
    // every accepted pre-upgrade socket as well as completed sessions so a
    // slow-header or invalid-upgrade flood cannot sit outside maxSessions.
    server.maxConnections = this.config.limits.maxSessions;
    server.headersTimeout = this.config.limits.handshakeTimeoutMs;
    server.requestTimeout = this.config.limits.handshakeTimeoutMs;
    server.keepAliveTimeout = 1000;
    // A rejected upgrade has no WebSocketPeer yet. Keep its reset/error path
    // owned by the listener rather than allowing EventEmitter to surface an
    // unhandled socket error during an invalid or slow HTTP handshake.
    server.on("error", () => {});
    server.on("connection", (socket) => {
      if (this.sockets.size >= this.config.limits.maxSessions) {
        socket.destroy();
        return;
      }
      socket.on("error", () => {});
      this.sockets.add(socket);
      socket.once("close", () => this.sockets.delete(socket));
    });
    server.on("upgrade", (request, socket, head) => {
      if (this.sessions.size >= this.config.limits.maxSessions) {
        rejectUpgrade(socket, "503 Service Unavailable");
        return;
      }
      if (!isValidUpgrade(request)) {
        rejectUpgrade(socket, "400 Bad Request");
        return;
      }
      // RFC 6455 subprotocol values are case-sensitive.  Requiring one exact
      // header value prevents an unrelated or multi-token negotiation from
      // being treated as WISP merely because it happens to include "wisp".
      if (request.headers["sec-websocket-protocol"] !== WISP_PROTOCOL) {
        rejectUpgrade(socket, "426 Upgrade Required");
        return;
      }
      const responseHeaders = [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        `Sec-WebSocket-Accept: ${websocketAcceptValue(request.headers["sec-websocket-key"])}`,
        `Sec-WebSocket-Protocol: ${WISP_PROTOCOL}`,
      ];
      socket.write(`${responseHeaders.join("\r\n")}\r\n\r\n`);
      let session = null;
      const peer = new WebSocketPeer(socket, this.config.limits, {
        onClosed: () => session?.peerClosed(),
        onMessage: (packet) => session?.receive(packet),
        onWritable: () => session?.writable(),
      });
      socket.setTimeout(this.config.limits.idleTimeoutMs);
      socket.once("timeout", () => peer.close(1001, "idle-timeout"));
      session = new WispSession(peer, this);
      this.sessions.add(session);
      peer.receiveInitial(head);
    });
    this.server = server;
    await new Promise((resolve, reject) => {
      const onError = (error) => {
        server.off("listening", onListening);
        reject(error);
      };
      const onListening = () => {
        server.off("error", onError);
        resolve();
      };
      server.once("error", onError);
      server.once("listening", onListening);
      // The public WSS terminator/forwarder is supplied by operator
      // infrastructure. This plain HTTP Upgrade process is intentionally
      // never internet-facing by itself.
      server.listen({
        exclusive: true,
        host: LOOPBACK_HOST,
        port: this.config.listenPort,
      });
    });
    const address = server.address();
    if (!address || typeof address === "string" ||
        address.address !== LOOPBACK_HOST || !Number.isSafeInteger(address.port) ||
        address.port < 1 || address.port > 65535) {
      await this.close();
      fail("public WISP gateway did not bind IPv4 loopback");
    }
    return {host: LOOPBACK_HOST, port: address.port, path: WISP_PATH};
  }

  async close() {
    const server = this.server;
    this.server = null;
    for (const session of [...this.sessions]) {
      session.peer.close(1001, "gateway-shutdown");
      session.close();
      session.peer.destroy();
    }
    for (const socket of this.sockets) {
      socket.destroy();
    }
    if (!server || !server.listening) {
      return;
    }
    await new Promise((resolve) => server.close(() => resolve()));
  }
}

export async function startPublicWispGateway(config, hooks = undefined) {
  const gateway = new PublicWispGateway(config, hooks);
  return {gateway, ...(await gateway.start())};
}

function parseArguments(argv) {
  if (argv.length !== 2 || argv[0] !== "--config") {
    fail("usage: m5_public_wisp_gateway.js --config /external/path.json");
  }
  return argv[1];
}

async function main() {
  const config = loadExternalPublicWispGatewayConfig(
      parseArguments(process.argv.slice(2)));
  const {gateway, host, path: endpointPath, port} =
      await startPublicWispGateway(config);
  // This is safe operator bootstrap metadata: it contains the loopback HTTP
  // listener only, never an approved hostname, public endpoint, URL,
  // credential, or destination transcript.
  process.stdout.write(`${JSON.stringify({
    listen_origin: `http://${host}:${port}`,
    path: endpointPath,
    schema_version: CONFIG_SCHEMA_VERSION,
  })}\n`);
  let stopping = false;
  const onInput = (data) => {
    if (String(data).split(/\r?\n/).includes("shutdown")) {
      void stop();
    }
  };
  const stop = async () => {
    if (stopping) {
      return;
    }
    stopping = true;
    await gateway.close();
    await new Promise((resolve) =>
      process.stdout.write('{"event":"stopped"}\n', resolve));
    // Releasing the resumed stdin watcher is necessary when this is managed
    // by a tunnel supervisor rather than a one-shot shell pipe. Server close
    // has already completed, so natural process exit cannot strand a carrier.
    process.stdin.removeListener("data", onInput);
    process.stdin.pause();
    process.stdin.unref?.();
    // The listener is only installed by this command-line supervisor. The
    // gateway and its sockets are fully closed and the final record flushed,
    // so an explicit exit here cannot truncate a live carrier or leave a
    // background process pinned by a parent-owned stdin pipe.
    process.exit(0);
  };
  process.stdin.setEncoding("utf8");
  process.stdin.resume();
  process.stdin.on("data", onInput);
  process.stdin.on("end", () => {});
  process.once("SIGINT", () => void stop());
  process.once("SIGTERM", () => void stop());
}

if (process.argv[1] &&
    import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => {
    // Do not serialize startup details such as configuration paths, public
    // targets, or TLS/forwarder material. The loopback availability category
    // is safe for a local supervisor and lets test infrastructure skip cleanly.
    const loopbackUnavailable = error &&
        ["EACCES", "EADDRINUSE", "EPERM"].includes(error.code);
    process.stderr.write(loopbackUnavailable ?
        "m5_public_wisp_gateway: loopback listener unavailable\n" :
        "m5_public_wisp_gateway: startup failed\n");
    process.exitCode = 2;
  });
}

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wire-level contract tests for the loopback-only M5 WISP fixture."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import struct
import subprocess
import time
import unittest
from urllib.parse import urlsplit
from urllib.request import urlopen


ROOT_DIR = Path(__file__).resolve().parents[3]
SERVER = ROOT_DIR / "tools/wasm/m5_wisp_test_server.js"
ROOT_CERTIFICATE = ROOT_DIR / "net/data/ssl/certificates/root_ca_cert.pem"
PINNED_NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"


def node_executable() -> str | None:
    path_node = shutil.which("node")
    if path_node:
        return path_node
    if PINNED_NODE.is_file():
        return str(PINNED_NODE)
    return None


def recv_exact(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise AssertionError("unexpected end of stream")
        data.extend(chunk)
    return bytes(data)


def read_http_headers(connection: socket.socket) -> tuple[str, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("unexpected end of HTTP response")
        data.extend(chunk)
        if len(data) > 64 * 1024:
            raise AssertionError("HTTP response headers are too large")
    header, remaining = bytes(data).split(b"\r\n\r\n", 1)
    return header.decode("latin-1"), remaining


def read_http_response(connection: socket.socket) -> tuple[str, bytes]:
    header, body = read_http_headers(connection)
    content_length = None
    for line in header.split("\r\n")[1:]:
        name, separator, value = line.partition(":")
        if separator and name.lower() == "content-length":
            content_length = int(value.strip())
            break
    if content_length is None:
        raise AssertionError("HTTP response omitted Content-Length")
    while len(body) < content_length:
        chunk = connection.recv(content_length - len(body))
        if not chunk:
            raise AssertionError("HTTP response ended before its body")
        body += chunk
    return header, body[:content_length]


class BufferedSocket:
    def __init__(self, connection: socket.socket, pending: bytes = b"") -> None:
        self.connection = connection
        self.pending = bytearray(pending)

    def read_exact(self, length: int) -> bytes:
        while len(self.pending) < length:
            chunk = self.connection.recv(4096)
            if not chunk:
                raise AssertionError("unexpected end of WebSocket stream")
            self.pending.extend(chunk)
        result = bytes(self.pending[:length])
        del self.pending[:length]
        return result


def read_websocket_frame(connection: BufferedSocket) -> tuple[bool, int, bytes]:
    first, second = connection.read_exact(2)
    finished = bool(first & 0x80)
    opcode = first & 0x0F
    if first & 0x70 or second & 0x80:
        raise AssertionError("server WebSocket frame violates RFC 6455")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", connection.read_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", connection.read_exact(8))[0]
    if length > 1024 * 1024 + 5:
        raise AssertionError("server WebSocket frame exceeds fixture bound")
    return finished, opcode, connection.read_exact(length)


def send_websocket_frame(
    connection: socket.socket,
    opcode: int,
    payload: bytes,
    *,
    finished: bool = True,
    masked: bool = True,
) -> None:
    first = opcode | (0x80 if finished else 0)
    mask_bit = 0x80 if masked else 0
    if len(payload) <= 125:
        header = bytes([first, mask_bit | len(payload)])
    elif len(payload) <= 0xFFFF:
        header = bytes([first, mask_bit | 126]) + struct.pack("!H", len(payload))
    else:
        header = bytes([first, mask_bit | 127]) + struct.pack("!Q", len(payload))
    if masked:
        mask = os.urandom(4)
        masked_payload = bytes(
            value ^ mask[index % 4] for index, value in enumerate(payload))
        connection.sendall(header + mask + masked_payload)
    else:
        connection.sendall(header + payload)


def wisp_packet(packet_type: int, stream_id: int, payload: bytes = b"") -> bytes:
    return bytes([packet_type]) + struct.pack("<I", stream_id) + payload


def parse_wisp_packet(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 5:
        raise AssertionError("WISP packet is shorter than its fixed header")
    return payload[0], struct.unpack("<I", payload[1:5])[0], payload[5:]


class M5WispTestServerTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        node = node_executable()
        if node is None:
            self.skipTest("Node is unavailable")
        self.process = subprocess.Popen(
            [node, str(SERVER), "--host-origin", "http://127.0.0.1:8765"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.process.stdout is not None
        first_line = self.process.stdout.readline().strip()
        if not first_line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            self.fail(f"fixture did not publish metadata: {stderr}")
        self.metadata = json.loads(first_line)

    def tearDown(self) -> None:
        if self.process.poll() is None:
            assert self.process.stdin is not None
            self.process.stdin.write("shutdown\n")
            self.process.stdin.flush()
            try:
                stdout, stderr = self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                stdout, stderr = self.process.communicate(timeout=10)
        else:
            stdout, stderr = self.process.communicate(timeout=10)
        self.shutdown_lines = [
            line.strip() for line in stdout.splitlines() if line.strip()
        ]
        self.shutdown_stderr = stderr

    def _endpoint(self, name: str) -> tuple[str, int, str]:
        parsed = urlsplit(self.metadata[name])
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertIsNotNone(parsed.port)
        return parsed.hostname or "", parsed.port or 0, parsed.path

    def _tls_connection(
        self, url_name: str, *, alpn: list[str] | None = None
    ) -> tuple[ssl.SSLSocket, object]:
        parsed = urlsplit(self.metadata[url_name])
        context = ssl.create_default_context(cafile=str(ROOT_CERTIFICATE))
        if alpn:
            context.set_alpn_protocols(alpn)
        raw = socket.create_connection(("127.0.0.1", parsed.port), timeout=5)
        connection = context.wrap_socket(raw, server_hostname="a.test")
        return connection, parsed

    def _plaintext_http_get(
        self, url_name: str, *, origin: str | None = None
    ) -> tuple[str, bytes, object]:
        parsed = urlsplit(self.metadata[url_name])
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "a.test")
        self.assertIsNotNone(parsed.port)
        raw = socket.create_connection(("127.0.0.1", parsed.port), timeout=5)
        with raw:
            request = (
                f"GET {parsed.path} HTTP/1.1\r\n"
                f"Host: a.test:{parsed.port}\r\n"
            )
            if origin is not None:
                request += f"Origin: {origin}\r\n"
            raw.sendall((request + "Connection: close\r\n\r\n").encode("ascii"))
            header, body = read_http_response(raw)
        return header, body, parsed

    def _status(self) -> dict[str, object]:
        with urlopen(self.metadata["transcriptUrl"], timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _wait_for_tls_failure_tcp_connection(self) -> dict[str, object]:
        deadline = time.monotonic() + 5
        status: dict[str, object] = {}
        while time.monotonic() < deadline:
            status = self._status()
            if status.get("tlsMismatchTcpConnections", 0) >= 1:
                return status
            time.sleep(0.05)
        self.fail("TLS failure endpoint did not observe a TCP connection")

    def _h2_resource(self) -> bytes:
        connection, parsed = self._tls_connection("httpsUrl", alpn=["h2"])
        with connection:
            self.assertEqual(connection.selected_alpn_protocol(), "h2")
            authority = f"a.test:{parsed.port}".encode("ascii")
            # HPACK: indexed :method GET/:scheme https, then literal :path
            # and :authority fields without dynamic-table indexing.
            header_block = (
                b"\x82\x87\x04\x0f/m5/h2-resource\x01" +
                bytes([len(authority)]) + authority)

            def frame(frame_type: int, flags: int, stream_id: int,
                      payload: bytes = b"") -> bytes:
                return (
                    len(payload).to_bytes(3, "big") +
                    bytes([frame_type, flags]) +
                    struct.pack("!I", stream_id & 0x7FFFFFFF) + payload)

            connection.sendall(
                b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n" +
                frame(0x04, 0x00, 0) + frame(0x01, 0x05, 1, header_block))
            body = bytearray()
            for _ in range(32):
                header = recv_exact(connection, 9)
                length = int.from_bytes(header[:3], "big")
                frame_type = header[3]
                flags = header[4]
                stream_id = struct.unpack("!I", header[5:])[0] & 0x7FFFFFFF
                payload = recv_exact(connection, length)
                if frame_type == 0x04 and flags == 0x00:
                    connection.sendall(frame(0x04, 0x01, 0))
                if frame_type == 0x00 and stream_id == 1:
                    body.extend(payload)
                    if flags & 0x01:
                        return bytes(body)
            self.fail("H2 response did not end its data stream")

    def _exercise_redirect_cookie_gate(self) -> dict[str, object]:
        node = node_executable()
        assert node is not None
        program = r'''
import fs from "node:fs";
import http2 from "node:http2";

const [redirectURL, rootCertificate, statusURL] = process.argv.slice(1);
const redirect = new URL(redirectURL);
const authority = `a.test:${redirect.port}`;
const session = http2.connect(`https://127.0.0.1:${redirect.port}`, {
  ca: fs.readFileSync(rootCertificate),
  servername: "a.test",
});

function get(path, headers = {}) {
  return new Promise((resolve, reject) => {
    const request = session.request({
      ":authority": authority,
      ":method": "GET",
      ":path": path,
      ...headers,
    });
    const chunks = [];
    let responseHeaders = null;
    request.once("response", (headers) => { responseHeaders = headers; });
    request.on("data", (chunk) => chunks.push(chunk));
    request.once("end", () => resolve({
      body: Buffer.concat(chunks).toString("utf8"),
      headers: responseHeaders,
    }));
    request.once("error", reject);
    request.end();
  });
}

try {
  const rejected = await get("/m5/");
  const redirected = await get(redirect.pathname);
  const setCookie = Array.isArray(redirected.headers["set-cookie"])
    ? redirected.headers["set-cookie"][0]
    : redirected.headers["set-cookie"];
  if (typeof setCookie !== "string") {
    throw new Error("redirect did not set a cookie");
  }
  const cookiePair = setCookie.split(";", 1)[0];
  const [cookieName] = cookiePair.split("=", 1);
  const wrongCookie = await get("/m5/", {
    cookie: `${cookieName}=wrong-value`,
  });
  const finalPage = await get("/m5/", {cookie: cookiePair});
  const statusText = await (await fetch(statusURL)).text();
  process.stdout.write(JSON.stringify({
    cookieAttributes: {
      httpOnly: setCookie.includes("HttpOnly"),
      pathM5: setCookie.includes("Path=/m5/"),
      sameSiteStrict: setCookie.includes("SameSite=Strict"),
      secure: setCookie.includes("Secure"),
    },
    cookieName,
    finalContentSecurityPolicy: finalPage.headers["content-security-policy"],
    finalHasFixture: finalPage.body.includes("Chromium Wasm M5 network fixture"),
    finalStatus: finalPage.headers[":status"],
    initialBody: rejected.body,
    initialStatus: rejected.headers[":status"],
    redirectLocation: redirected.headers.location,
    redirectStatus: redirected.headers[":status"],
    statusContainsCookie: statusText.includes(cookiePair),
    wrongCookieBody: wrongCookie.body,
    wrongCookieStatus: wrongCookie.headers[":status"],
  }));
} finally {
  session.close();
}
'''
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                program,
                self.metadata["redirectUrl"],
                str(ROOT_CERTIFICATE),
                self.metadata["transcriptUrl"],
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            self.fail(
                "redirect-cookie H2 client failed: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return json.loads(result.stdout)

    def _exercise_cache_revalidation(self, mode: str) -> dict[str, object]:
        node = node_executable()
        assert node is not None
        program = r'''
import fs from "node:fs";
import http2 from "node:http2";

const [httpsURL, rootCertificate, mode] = process.argv.slice(1);
const target = new URL(httpsURL);
const authority = `a.test:${target.port}`;
const session = http2.connect(`https://127.0.0.1:${target.port}`, {
  ca: fs.readFileSync(rootCertificate),
  servername: "a.test",
});

function get(headers = {}) {
  return new Promise((resolve, reject) => {
    const request = session.request({
      ":authority": authority,
      ":method": "GET",
      ":path": "/m5/cache-revalidate",
      ...headers,
    });
    const chunks = [];
    let responseHeaders = null;
    request.once("response", (headers) => { responseHeaders = headers; });
    request.on("data", (chunk) => chunks.push(chunk));
    request.once("end", () => resolve({
      body: Buffer.concat(chunks).toString("utf8"),
      headers: responseHeaders,
    }));
    request.once("error", reject);
    request.end();
  });
}

try {
  if (mode === "saturate") {
    const statuses = [];
    for (let index = 0; index < 20; index += 1) {
      const response = await get();
      statuses.push(response.headers[":status"]);
    }
    process.stdout.write(JSON.stringify({statuses}));
  } else {
    const stored = await get();
    const etag = stored.headers.etag;
    if (typeof etag !== "string") {
      throw new Error("cache store did not return an ETag");
    }
    const validator = mode === "exact" ? etag : '"m5-cache-wrong"';
    const revalidated = await get({"if-none-match": validator});
    process.stdout.write(JSON.stringify({
      cacheControl: stored.headers["cache-control"],
      etag,
      revalidateBody: revalidated.body,
      revalidateETag: revalidated.headers.etag,
      revalidateHasContentLength:
        Object.hasOwn(revalidated.headers, "content-length"),
      revalidateState: revalidated.headers["x-m5-cache-state"],
      revalidateStatus: revalidated.headers[":status"],
      storeBody: stored.body,
      storeState: stored.headers["x-m5-cache-state"],
      storeStatus: stored.headers[":status"],
    }));
  }
} finally {
  session.close();
}
'''
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                program,
                self.metadata["httpsUrl"],
                str(ROOT_CERTIFICATE),
                mode,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            self.fail(
                "cache-revalidation H2 client failed: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return json.loads(result.stdout)

    def _exercise_cancel_stream(self) -> dict[str, object]:
        node = node_executable()
        assert node is not None
        program = r'''
import fs from "node:fs";
import http2 from "node:http2";

const [httpsURL, rootCertificate] = process.argv.slice(1);
const target = new URL(httpsURL);
const authority = `a.test:${target.port}`;
const session = http2.connect(`https://127.0.0.1:${target.port}`, {
  ca: fs.readFileSync(rootCertificate),
  servername: "a.test",
});

function get(path) {
  return new Promise((resolve, reject) => {
    const request = session.request({
      ":authority": authority,
      ":method": "GET",
      ":path": path,
    });
    const chunks = [];
    let headers = null;
    request.once("response", (value) => { headers = value; });
    request.on("data", (chunk) => chunks.push(chunk));
    request.once("end", () => resolve({
      body: Buffer.concat(chunks).toString("utf8"),
      headers,
    }));
    request.once("error", reject);
    request.end();
  });
}

try {
  const cancelled = await new Promise((resolve, reject) => {
    const request = session.request({
      ":authority": authority,
      ":method": "GET",
      ":path": "/m5/cancel-stream",
    });
    let firstChunk = "";
    let responseStatus = null;
    let sentCancel = false;
    const timeout = setTimeout(() => reject(new Error("cancel stream timeout")),
        5000);
    request.once("response", (headers) => {
      responseStatus = headers[":status"];
    });
    request.on("data", (chunk) => {
      firstChunk += chunk.toString("utf8");
      if (!sentCancel) {
        sentCancel = true;
        request.close(http2.constants.NGHTTP2_CANCEL);
      }
    });
    request.once("close", () => {
      clearTimeout(timeout);
      resolve({firstChunk, responseStatus, sentCancel});
    });
    request.once("error", reject);
    request.end();
  });
  const proof = await get("/m5/cancel-proof");
  process.stdout.write(JSON.stringify({
    ...cancelled,
    proofBody: proof.body,
    proofStatus: proof.headers[":status"],
  }));
} finally {
  session.close();
}
'''
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                program,
                self.metadata["httpsUrl"],
                str(ROOT_CERTIFICATE),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            self.fail(
                "cancel-stream H2 client failed: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return json.loads(result.stdout)

    def _exercise_cancel_stream_session_mismatch(self) -> dict[str, object]:
        node = node_executable()
        assert node is not None
        program = r'''
import fs from "node:fs";
import http2 from "node:http2";

const [httpsURL, rootCertificate] = process.argv.slice(1);
const target = new URL(httpsURL);
const authority = `a.test:${target.port}`;
const sessionOptions = {
  ca: fs.readFileSync(rootCertificate),
  servername: "a.test",
};

function createSession() {
  return http2.connect(`https://127.0.0.1:${target.port}`, sessionOptions);
}

function get(session, path) {
  return new Promise((resolve, reject) => {
    const request = session.request({
      ":authority": authority,
      ":method": "GET",
      ":path": path,
    });
    const chunks = [];
    let headers = null;
    request.once("response", (value) => { headers = value; });
    request.on("data", (chunk) => chunks.push(chunk));
    request.once("end", () => resolve({
      body: Buffer.concat(chunks).toString("utf8"),
      headers,
    }));
    request.once("error", reject);
    request.end();
  });
}

const primary = createSession();
const secondary = createSession();
try {
  const request = primary.request({
    ":authority": authority,
    ":method": "GET",
    ":path": "/m5/cancel-stream",
  });
  let firstChunk = "";
  const firstChunkReady = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("first chunk timeout")),
        5000);
    request.once("response", (headers) => {
      if (headers[":status"] !== 200) {
        reject(new Error(`unexpected cancel status ${headers[":status"]}`));
      }
    });
    request.once("data", (chunk) => {
      firstChunk += chunk.toString("utf8");
      clearTimeout(timeout);
      resolve();
    });
    request.once("error", reject);
  });
  const closed = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("cancel close timeout")),
        5000);
    request.once("close", () => {
      clearTimeout(timeout);
      resolve();
    });
  });
  request.end();
  await firstChunkReady;
  const mismatch = await get(secondary, "/m5/cancel-proof");
  request.close(http2.constants.NGHTTP2_CANCEL);
  await closed;
  const proof = await get(primary, "/m5/cancel-proof");
  process.stdout.write(JSON.stringify({
    firstChunk,
    mismatchBody: mismatch.body,
    mismatchStatus: mismatch.headers[":status"],
    proofBody: proof.body,
    proofStatus: proof.headers[":status"],
  }));
} finally {
  primary.close();
  secondary.close();
}
'''
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                program,
                self.metadata["httpsUrl"],
                str(ROOT_CERTIFICATE),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            self.fail(
                "cancel-stream session-mismatch H2 client failed: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return json.loads(result.stdout)

    def _exercise_slow_stream(
        self, *, mismatch_mode: str = "normal"
    ) -> dict[str, object]:
        node = node_executable()
        assert node is not None
        program = r'''
import fs from "node:fs";
import http2 from "node:http2";

const [httpsURL, rootCertificate, mismatchMode] = process.argv.slice(1);
const target = new URL(httpsURL);
const authority = `a.test:${target.port}`;
const sessionOptions = {
  ca: fs.readFileSync(rootCertificate),
  servername: "a.test",
};

function createSession() {
  return http2.connect(`https://127.0.0.1:${target.port}`, sessionOptions);
}

function get(session, path) {
  return new Promise((resolve, reject) => {
    const request = session.request({
      ":authority": authority,
      ":method": "GET",
      ":path": path,
    });
    const chunks = [];
    let headers = null;
    request.once("response", (value) => { headers = value; });
    request.on("data", (chunk) => chunks.push(chunk));
    request.once("end", () => resolve({
      body: Buffer.concat(chunks).toString("utf8"),
      headers,
    }));
    request.once("error", reject);
    request.end();
  });
}

function openSlowStream(session) {
  const request = session.request({
    ":authority": authority,
    ":method": "GET",
    ":path": "/m5/slow-stream",
  });
  let responseHeaders = null;
  let ended = false;
  let waiter = null;
  const chunks = [];
  let finish;
  let fail;
  const finished = new Promise((resolve, reject) => {
    finish = resolve;
    fail = reject;
  });
  const response = new Promise((resolve, reject) => {
    request.once("response", (headers) => {
      responseHeaders = headers;
      resolve(headers);
    });
    request.once("error", reject);
  });
  request.on("data", (chunk) => {
    chunks.push({bytes: Buffer.from(chunk), atMs: performance.now()});
    if (waiter) {
      const current = waiter;
      waiter = null;
      current.resolve();
    }
  });
  request.once("end", () => {
    ended = true;
    if (waiter) {
      const current = waiter;
      waiter = null;
      current.reject(new Error("slow stream ended before next stage"));
    }
    finish();
  });
  request.once("error", (error) => {
    if (waiter) {
      const current = waiter;
      waiter = null;
      current.reject(error);
    }
    fail(error);
  });
  request.end();
  async function waitForChunk() {
    if (chunks.length > 0) {
      return;
    }
    if (ended) {
      throw new Error("slow stream ended before the expected bytes arrived");
    }
    await new Promise((resolve, reject) => { waiter = {resolve, reject}; });
  }
  async function readExact(length) {
    const pieces = [];
    let remaining = length;
    let atMs = 0;
    while (remaining > 0) {
      await waitForChunk();
      const current = chunks[0];
      const count = Math.min(remaining, current.bytes.length);
      pieces.push(current.bytes.subarray(0, count));
      atMs = current.atMs;
      remaining -= count;
      if (count === current.bytes.length) {
        chunks.shift();
      } else {
        current.bytes = current.bytes.subarray(count);
      }
    }
    return {bytes: Buffer.concat(pieces, length), atMs};
  }
  return {
    response,
    finished,
    responseStatus: () => responseHeaders?.[":status"] ?? null,
    readExact,
    remainingBytes: () => chunks.reduce(
        (total, entry) => total + entry.bytes.length, 0),
  };
}

const primary = createSession();
const secondary = mismatchMode === "normal" ? null : createSession();
try {
  const slow = openSlowStream(primary);
  await slow.response;
  const first = await slow.readExact(Buffer.byteLength("M5_SLOW_STREAM_FIRST_STAGE"));
  const firstMismatch = mismatchMode === "first-ack" ? await get(
      secondary, "/m5/slow-stream-first-stage-ack") : null;
  const firstAck = await get(primary, "/m5/slow-stream-first-stage-ack");
  const second = await slow.readExact(Buffer.byteLength("M5_SLOW_STREAM_SECOND_STAGE"));
  const pauseReady = await get(
      primary, "/m5/slow-stream-consumer-pause-ready");
  const consumerPauseStartedAt = performance.now();
  await new Promise((resolve) => setTimeout(resolve, 150));
  const consumerBurst = await slow.readExact(64 * 1024);
  const consumerPauseElapsedMs = performance.now() - consumerPauseStartedAt;
  const consumerResume = await get(
      primary, "/m5/slow-stream-consumer-resume");
  const secondMismatch = mismatchMode === "second-ack" ? await get(
      secondary, "/m5/slow-stream-second-stage-ack") : null;
  const secondAck = await get(primary, "/m5/slow-stream-second-stage-ack");
  const third = await slow.readExact(Buffer.byteLength("M5_SLOW_STREAM_THIRD_STAGE"));
  await slow.finished;
  const proofMismatch = mismatchMode === "proof" ? await get(
      secondary, "/m5/slow-stream-proof") : null;
  const proof = await get(primary, "/m5/slow-stream-proof");
  const mismatch = firstMismatch || secondMismatch || proofMismatch;
  process.stdout.write(JSON.stringify({
    consumerBurstAllExpectedBytes: consumerBurst.bytes.every(
        (value) => value === 0x53),
    consumerBurstBytes: consumerBurst.bytes.length,
    consumerPauseElapsedMs,
    consumerPauseReadyBody: pauseReady.body,
    consumerPauseReadyStatus: pauseReady.headers[":status"],
    consumerResumeBody: consumerResume.body,
    consumerResumeStatus: consumerResume.headers[":status"],
    firstAckBody: firstAck.body,
    firstAckStatus: firstAck.headers[":status"],
    firstStage: first.bytes.toString("utf8"),
    mismatchBody: mismatch?.body ?? null,
    mismatchStatus: mismatch?.headers?.[":status"] ?? null,
    responseStatus: slow.responseStatus(),
    remainingBytes: slow.remainingBytes(),
    secondAckBody: secondAck.body,
    secondAckStatus: secondAck.headers[":status"],
    secondDelayMs: second.atMs - first.atMs,
    secondStage: second.bytes.toString("utf8"),
    thirdDelayMs: third.atMs - second.atMs,
    thirdStage: third.bytes.toString("utf8"),
    proofBody: proof.body,
    proofStatus: proof.headers[":status"],
  }));
} finally {
  primary.close();
  secondary?.close();
}
'''
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                program,
                self.metadata["httpsUrl"],
                str(ROOT_CERTIFICATE),
                mismatch_mode,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            self.fail(
                "slow-stream H2 client failed: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return json.loads(result.stdout)

    def _exercise_large_download(self) -> dict[str, object]:
        node = node_executable()
        assert node is not None
        program = r'''
import fs from "node:fs";
import http2 from "node:http2";

const [httpsURL, rootCertificate] = process.argv.slice(1);
const target = new URL(httpsURL);
const authority = `a.test:${target.port}`;
const session = http2.connect(`https://127.0.0.1:${target.port}`, {
  ca: fs.readFileSync(rootCertificate),
  servername: "a.test",
});

try {
  const result = await new Promise((resolve, reject) => {
    const request = session.request({
      ":authority": authority,
      ":method": "GET",
      ":path": "/m5/large-download",
    });
    let headers = null;
    let bytes = 0;
    let chunks = 0;
    let exactBytes = true;
    request.once("response", (value) => { headers = value; });
    request.on("data", (chunk) => {
      const data = Buffer.from(chunk);
      for (let index = 0; index < data.length; ++index) {
        if (data[index] !== ((bytes + index) & 0xff)) {
          exactBytes = false;
        }
      }
      bytes += data.length;
      chunks += 1;
    });
    request.once("end", () => resolve({
      bytes,
      chunks,
      contentDisposition: headers?.["content-disposition"] ?? null,
      contentLength: headers?.["content-length"] ?? null,
      exactBytes,
      responseStatus: headers?.[":status"] ?? null,
    }));
    request.once("error", reject);
    request.end();
  });
  process.stdout.write(JSON.stringify(result));
} finally {
  session.close();
}
'''
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                program,
                self.metadata["httpsUrl"],
                str(ROOT_CERTIFICATE),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            self.fail(
                "large-download H2 client failed: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return json.loads(result.stdout)

    def test_source_is_es_module_and_keeps_key_out_of_output_contract(self) -> None:
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn('import http2 from "node:http2"', source)
        self.assertIn("WISP_STREAM_OPEN_CONFIRMATION_EXTENSION", source)
        self.assertIn("payload[0] !== 0x01", source)
        self.assertIn("host: LOOPBACK_HOST", source)
        self.assertIn("MAX_WEBSOCKET_MESSAGE_BYTES", source)
        self.assertIn(
            "window.__chromiumWasmM5Probe = () => JSON.stringify({", source)
        self.assertIn('h2Response.headers.get("alt-svc")', source)
        self.assertIn("TLS_FAILURE_CERTIFICATE_PATH", source)
        self.assertIn("tls-failure-tcp-connect", source)
        self.assertIn("tls-failure-http-request", source)
        self.assertIn("REDIRECT_COOKIE_NAME", source)
        self.assertIn("HttpOnly", source)
        self.assertIn("SameSite=Strict", source)
        self.assertIn("h2-redirect-cookie", source)
        self.assertIn("h2-page-cookie", source)
        self.assertIn("CACHE_REVALIDATE_ETAG", source)
        self.assertIn("h2-cache-store-200", source)
        self.assertIn("h2-cache-revalidate-304", source)
        self.assertIn("cspConnectSrcTargetUrl", source)
        self.assertIn("securitypolicyviolation", source)
        self.assertIn('event.disposition === "enforce"', source)
        self.assertIn("event.blockedURI === cspConnectSrcTargetURL", source)
        self.assertIn("h2-csp-connect-src-proof", source)
        self.assertIn("csp-connect-src-target-tcp-connect", source)
        self.assertIn("plaintextHttpControlUrl", source)
        self.assertIn("plaintextHttpControlProofUrl", source)
        self.assertIn("mixedContentTargetUrl", source)
        self.assertIn(
            "window.__chromiumWasmM5PlaintextHttpControlProbe", source
        )
        self.assertIn('phase: "plaintext-http-control"', source)
        self.assertIn('phase: "https-fixture"', source)
        self.assertIn("activeMixedContentCspAllowed", source)
        self.assertIn('activeMixedContentErrorName !== "TypeError"', source)
        self.assertIn("h2-mixed-content-proof", source)
        self.assertIn("CANCEL_STREAM_FIRST_CHUNK", source)
        self.assertIn("CANCEL_STREAM_PROOF_BODY", source)
        self.assertIn('requestPath === "/m5/cancel-stream"', source)
        self.assertIn('requestPath === "/m5/cancel-proof"', source)
        self.assertIn("AbortController", source)
        self.assertIn("await reader.read()", source)
        self.assertIn("NGHTTP2_CANCEL", source)
        self.assertIn("isCancelStreamProofSession", source)
        self.assertIn("stream.session === context.cancelStreamSession", source)
        self.assertIn("cancelStreamProofSessionMismatches", source)
        self.assertIn("h2-cancel-stream-cancel-reset", source)
        self.assertIn("h2-cancel-stream-proof", source)
        self.assertIn("SLOW_STREAM_STAGES", source)
        self.assertIn('requestPath === "/m5/slow-stream"', source)
        self.assertIn('requestPath === "/m5/slow-stream-first-stage-ack"', source)
        self.assertIn('requestPath === "/m5/slow-stream-second-stage-ack"', source)
        self.assertIn(
            'requestPath === "/m5/slow-stream-consumer-pause-ready"', source
        )
        self.assertIn(
            'requestPath === "/m5/slow-stream-consumer-resume"', source
        )
        self.assertIn('requestPath === "/m5/slow-stream-proof"', source)
        self.assertIn("verifySlowStream", source)
        self.assertIn("readExactSlowStreamStage", source)
        self.assertIn("SLOW_STREAM_STAGE_DELAY_MS", source)
        self.assertIn("SLOW_STREAM_CONSUMER_BURST_BYTES", source)
        self.assertIn("readExactSlowStreamConsumerBurst", source)
        self.assertIn("handleSlowStreamConsumerPauseReady", source)
        self.assertIn("handleSlowStreamConsumerResume", source)
        self.assertIn("isSlowStreamSession", source)
        self.assertIn("stream.session === context.slowStreamSession", source)
        self.assertIn("h2-slow-stream-first-stage-ack", source)
        self.assertIn("h2-slow-stream-proof", source)
        self.assertIn("LARGE_DOWNLOAD_BYTES", source)
        self.assertIn('requestPath === "/m5/large-download"', source)
        self.assertIn("writeLargeDownload", source)
        self.assertIn("content-disposition", source)
        self.assertIn("h2-large-download-complete", source)
        self.assertIn('document.createElement("iframe")', source)
        self.assertIn("frame.src = largeDownloadURL", source)
        self.assertIn("largeDownloadNavigationRequested", source)
        self.assertIn("largeDownloadNativeComplete", source)
        self.assertIn("__chromiumWasmM5NativeDownloadComplete", source)
        self.assertNotIn("fetch(largeDownloadURL", source)
        self.assertIn("RECONNECT_STREAM_FIRST_CHUNK", source)
        self.assertIn('requestPath === "/m5/reconnect-stream"', source)
        self.assertIn("handleReconnectFirstChunkAck", source)
        self.assertIn('requestPath === "/m5/reconnect-recovery"', source)
        self.assertIn("wispClosePacket(", source)
        self.assertIn("WISP_CLOSE_REASONS.NETWORK_ERROR", source)
        reconnect_disconnect = source.split(
            "function scheduleReconnectDisconnect(context) {", 1
        )[1].split("\nfunction handleReconnectFirstChunkAck", 1)[0]
        self.assertIn(
            'relay.peer.close(1000, "m5-carrier-close")',
            reconnect_disconnect,
        )
        self.assertIn("h2-reconnect-carrier-close", reconnect_disconnect)
        self.assertNotIn("wispClosePacket(", reconnect_disconnect)
        self.assertNotIn("relay.peer.destroy()", reconnect_disconnect)
        self.assertIn("h2-reconnect-stream-disconnected", source)
        self.assertIn("h2-reconnect-wisp-disconnected", source)
        self.assertIn("h2-reconnect-recovery", source)
        self.assertIn("holdReconnectRecovery", source)
        self.assertIn("resolvePendingReconnectRecovery", source)
        self.assertIn("RECONNECT_RECOVERY_TIMEOUT_MS", source)
        self.assertIn("${RECONNECT_ACK_TIMEOUT_MS}", source)
        self.assertIn("${RECONNECT_STREAM_FAILURE_TIMEOUT_MS}", source)
        self.assertIn("ack?.ok === true", source)
        self.assertIn(
            "mixed-content-target-post-control-wisp-connect", source
        )
        self.assertNotIn("upgrade-insecure-requests", source)
        self.assertNotIn("block-all-mixed-content", source)
        self.assertNotIn("BEGIN PRIVATE KEY", source)
        self.assertNotIn("PRIVATE KEY", json.dumps(self.metadata))

    def test_metadata_h2_h1_wss_and_sanitized_status_contract(self) -> None:
        self.assertEqual(self.metadata["fixture"], "chromium-wasm-m5-network-v1")
        self.assertEqual(self.metadata["protocol"], 1)
        self.assertEqual(self.metadata["schema_version"], 1)
        self.assertEqual(urlsplit(self.metadata["wispEndpoint"]).scheme, "ws")
        self.assertEqual(urlsplit(self.metadata["wispEndpoint"]).path, "/wisp/")
        self.assertEqual(urlsplit(self.metadata["httpsUrl"]).scheme, "https")
        self.assertEqual(urlsplit(self.metadata["httpsUrl"]).hostname, "a.test")
        self.assertEqual(urlsplit(self.metadata["httpsUrl"]).path, "/m5/")
        redirect_url = urlsplit(self.metadata["redirectUrl"])
        self.assertEqual(redirect_url.scheme, "https")
        self.assertEqual(redirect_url.hostname, "a.test")
        self.assertEqual(redirect_url.path, "/m5/redirect-cookie")
        self.assertEqual(
            redirect_url.port, urlsplit(self.metadata["httpsUrl"]).port)
        tls_failure_url = urlsplit(self.metadata["tlsFailureUrl"])
        self.assertEqual(tls_failure_url.scheme, "https")
        self.assertEqual(tls_failure_url.hostname, "a.test")
        self.assertEqual(tls_failure_url.path, "/m5/tls-name-mismatch")
        self.assertIsNotNone(tls_failure_url.port)
        self.assertNotEqual(
            tls_failure_url.port, urlsplit(self.metadata["httpsUrl"]).port)
        plaintext_control_url = urlsplit(
            self.metadata["plaintextHttpControlUrl"]
        )
        plaintext_control_proof_url = urlsplit(
            self.metadata["plaintextHttpControlProofUrl"]
        )
        mixed_content_target_url = urlsplit(
            self.metadata["mixedContentTargetUrl"]
        )
        self.assertEqual(plaintext_control_url.scheme, "http")
        self.assertEqual(plaintext_control_url.hostname, "a.test")
        self.assertEqual(
            plaintext_control_url.path, "/m5/plaintext-control"
        )
        self.assertEqual(plaintext_control_proof_url.scheme, "http")
        self.assertEqual(plaintext_control_proof_url.hostname, "a.test")
        self.assertEqual(
            plaintext_control_proof_url.path, "/m5/plaintext-control-proof"
        )
        self.assertEqual(mixed_content_target_url.scheme, "http")
        self.assertEqual(mixed_content_target_url.hostname, "a.test")
        self.assertEqual(
            mixed_content_target_url.path, "/m5/mixed-content-target"
        )
        self.assertIsNotNone(plaintext_control_url.port)
        self.assertEqual(
            plaintext_control_proof_url.port, plaintext_control_url.port
        )
        self.assertEqual(
            mixed_content_target_url.port, plaintext_control_url.port
        )
        self.assertNotIn(
            plaintext_control_url.port,
            {
                urlsplit(self.metadata["httpsUrl"]).port,
                urlsplit(self.metadata["http1Url"]).port,
                tls_failure_url.port,
            },
        )
        csp_target_url = urlsplit(self.metadata["cspConnectSrcTargetUrl"])
        self.assertEqual(csp_target_url.scheme, "https")
        self.assertEqual(csp_target_url.hostname, "a.test")
        self.assertEqual(csp_target_url.path, "/m5/csp-connect-src-target")
        self.assertIsNotNone(csp_target_url.port)
        self.assertNotIn(
            csp_target_url.port,
            {
                urlsplit(self.metadata["httpsUrl"]).port,
                urlsplit(self.metadata["http1Url"]).port,
                plaintext_control_url.port,
                tls_failure_url.port,
            },
        )
        self.assertEqual(self.metadata["statusUrl"], self.metadata["transcriptUrl"])

        h1_connection, h1_url = self._tls_connection("http1Url")
        with h1_connection:
            h1_connection.sendall(
                b"GET /m5/cors-resource HTTP/1.1\r\n" +
                f"Host: a.test:{h1_url.port}\r\n".encode("ascii") +
                f"Origin: https://a.test:{urlsplit(self.metadata['httpsUrl']).port}\r\n".encode("ascii") +
                b"Connection: close\r\n\r\n")
            header, body = read_http_headers(h1_connection)
            self.assertIn("HTTP/1.1 200", header)
            self.assertIn("X-M5-HTTP-Version: http/1.1", header)
            self.assertEqual(body, b"M5_CORS_OK")

        self.assertEqual(self._h2_resource(), b"M5_H2_OK")

        wss_connection, wss_url = self._tls_connection("webSocketUrl")
        with wss_connection:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            page_origin = (
                f"https://a.test:{urlsplit(self.metadata['httpsUrl']).port}")
            wss_connection.sendall(
                b"GET /m5/ws HTTP/1.1\r\n" +
                f"Host: a.test:{wss_url.port}\r\n".encode("ascii") +
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n" +
                f"Origin: {page_origin}\r\n".encode("ascii") +
                f"Sec-WebSocket-Key: {key}\r\n".encode("ascii") +
                b"Sec-WebSocket-Version: 13\r\n\r\n")
            header, pending = read_http_headers(wss_connection)
            self.assertIn("101 Switching Protocols", header)
            peer = BufferedSocket(wss_connection, pending)
            send_websocket_frame(wss_connection, 0x01, b"m5-echo")
            finished, opcode, payload = read_websocket_frame(peer)
            self.assertTrue(finished)
            self.assertEqual((opcode, payload), (0x01, b"m5-echo"))
            send_websocket_frame(wss_connection, 0x08, struct.pack("!H", 1000))
            _, opcode, _ = read_websocket_frame(peer)
            self.assertEqual(opcode, 0x08)

        status = self._status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["h2Requests"]["protocol"], "h2")
        self.assertGreaterEqual(status["h2Requests"]["count"], 1)
        self.assertEqual(status["corsRequests"], 1)
        self.assertEqual(status["webSocketEchoes"], 1)
        self.assertEqual(status["cacheStore200s"], 0)
        self.assertEqual(status["cacheConditionalRequests"], 0)
        self.assertEqual(status["cacheNotModified304s"], 0)
        self.assertEqual(status["cacheUnexpectedRequests"], 0)
        self.assertEqual(status["cspConnectSrcProofs"], 0)
        self.assertEqual(status["cspConnectSrcTargetTcpConnections"], 0)
        self.assertEqual(status["cspConnectSrcTargetRequests"], 0)
        self.assertEqual(status["mixedContentProofs"], 0)
        self.assertEqual(status["mixedContentTargetPostControlWispConnects"], 0)
        self.assertEqual(
            status["mixedContentTargetPostControlTcpConnections"], 0
        )
        self.assertEqual(status["mixedContentTargetPostControlRequests"], 0)
        self.assertEqual(status["plaintextHttpControlPhase"], "pre-control")
        self.assertEqual(status["plaintextHttpControlTcpConnections"], 0)
        self.assertEqual(status["plaintextHttpControlRequests"], 0)
        self.assertEqual(status["plaintextHttpControlProofs"], 0)
        self.assertEqual(status["redirectRequests"], 0)
        self.assertEqual(status["redirectCookieValidations"], 0)
        self.assertEqual(status["tlsMismatchTcpConnections"], 0)
        self.assertEqual(status["tlsMismatchHttpStreams"], 0)
        self.assertEqual(status["relayErrors"], 0)
        self.assertNotIn("m5_redirect=", json.dumps(status))
        self.assertNotIn("PRIVATE KEY", json.dumps(status))

    def test_csp_connect_src_target_is_tls_and_cors_readable(self) -> None:
        connection, target_url = self._tls_connection("cspConnectSrcTargetUrl")
        expected_body = b"M5_CSP_CONNECT_SRC_TARGET_UNEXPECTED"
        page_origin = (
            f"https://a.test:{urlsplit(self.metadata['httpsUrl']).port}")
        with connection:
            connection.sendall(
                b"GET /m5/csp-connect-src-target HTTP/1.1\r\n" +
                f"Host: a.test:{target_url.port}\r\n".encode("ascii") +
                f"Origin: {page_origin}\r\n".encode("ascii") +
                b"Connection: close\r\n\r\n")
            header, body = read_http_headers(connection)
            self.assertIn("HTTP/1.1 200", header)
            self.assertIn(
                f"Access-Control-Allow-Origin: {page_origin}", header)
            self.assertIn("X-M5-CSP-Connect-Src-Target: reached", header)
            while len(body) < len(expected_body):
                chunk = connection.recv(len(expected_body) - len(body))
                if not chunk:
                    self.fail("CSP target response ended before its body")
                body += chunk
        self.assertEqual(body, expected_body)

        status = self._status()
        self.assertEqual(status["cspConnectSrcTargetTcpConnections"], 1)
        self.assertEqual(status["cspConnectSrcTargetRequests"], 1)
        self.assertEqual(status["cspConnectSrcProofs"], 0)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertIn("csp-connect-src-target-tcp-connect", events)
        self.assertIn("h1-csp-connect-src-target-request", events)

    def test_plaintext_http_control_flips_phase_and_target_is_cors_readable(
        self,
    ) -> None:
        page_origin = (
            f"https://a.test:{urlsplit(self.metadata['httpsUrl']).port}"
        )
        rejected_proof_header, rejected_proof_body, _ = (
            self._plaintext_http_get("plaintextHttpControlProofUrl")
        )
        self.assertIn("HTTP/1.1 409", rejected_proof_header)
        self.assertIn(
            "X-M5-Plaintext-Control: proof-rejected", rejected_proof_header
        )
        self.assertEqual(
            rejected_proof_body, b"M5_PLAINTEXT_CONTROL_PROOF_REJECTED"
        )
        rejected_proof_status = self._status()
        self.assertEqual(
            rejected_proof_status["plaintextHttpControlPhase"], "pre-control"
        )
        self.assertEqual(
            rejected_proof_status["plaintextHttpControlRequests"], 0
        )
        self.assertEqual(
            rejected_proof_status["plaintextHttpControlProofs"], 0
        )

        control_header, control_body, control_url = self._plaintext_http_get(
            "plaintextHttpControlUrl"
        )
        self.assertIn("HTTP/1.1 200", control_header)
        self.assertIn("Content-Type: text/html; charset=utf-8", control_header)
        self.assertIn("X-M5-HTTP-Version: http/1.1", control_header)
        self.assertIn("X-M5-Plaintext-Control: document", control_header)
        self.assertNotIn("Strict-Transport-Security", control_header)
        self.assertIn(
            b"window.__chromiumWasmM5PlaintextHttpControlProbe", control_body
        )
        self.assertIn(b'phase: "plaintext-http-control"', control_body)
        self.assertIn(b"timerTicks: state.timerTicks", control_body)
        self.assertIn(
            b"state.timerTicks = Math.min(state.timerTicks + 1, 1000)",
            control_body,
        )
        self.assertIn(b"plaintextHttpControlDocument: true", control_body)
        self.assertIn(
            b"plaintextHttpControlProof: state.plaintextHttpControlProof",
            control_body,
        )
        control_script = control_body.split(b"<script>\n", 1)[1].split(
            b"\n</script>", 1
        )[0].decode("utf-8")
        node = node_executable()
        assert node is not None
        parsed_control_script = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                "new Function(process.argv[1]);",
                control_script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if parsed_control_script.returncode != 0:
            self.fail(
                "plaintext control page script did not parse: "
                f"{parsed_control_script.stderr!r}"
            )

        before_proof = self._status()
        self.assertEqual(
            before_proof["plaintextHttpControlPhase"], "pre-control"
        )
        self.assertEqual(before_proof["plaintextHttpControlRequests"], 1)
        self.assertEqual(before_proof["plaintextHttpControlProofs"], 0)
        self.assertGreaterEqual(
            before_proof["plaintextHttpControlTcpConnections"], 1
        )
        self.assertEqual(
            before_proof["mixedContentTargetPostControlWispConnects"], 0
        )
        self.assertEqual(
            before_proof["mixedContentTargetPostControlTcpConnections"], 0
        )
        self.assertEqual(
            before_proof["mixedContentTargetPostControlRequests"], 0
        )

        proof_header, proof_body, proof_url = self._plaintext_http_get(
            "plaintextHttpControlProofUrl"
        )
        self.assertEqual(proof_url.port, control_url.port)
        self.assertIn("HTTP/1.1 200", proof_header)
        self.assertIn("X-M5-Plaintext-Control: proof", proof_header)
        self.assertEqual(proof_body, b"M5_PLAINTEXT_CONTROL_PROOF")

        after_proof = self._status()
        self.assertEqual(
            after_proof["plaintextHttpControlPhase"], "post-control"
        )
        self.assertEqual(after_proof["plaintextHttpControlRequests"], 1)
        self.assertEqual(after_proof["plaintextHttpControlProofs"], 1)
        self.assertGreaterEqual(
            after_proof["plaintextHttpControlTcpConnections"], 1
        )
        self.assertEqual(
            after_proof["mixedContentTargetPostControlWispConnects"], 0
        )
        events = [
            entry.get("event")
            for entry in after_proof["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertIn("h1-plaintext-http-control", events)
        self.assertIn("h1-plaintext-http-control-proof", events)
        self.assertIn("plaintext-http-control-phase-complete", events)
        self.assertLess(
            events.index("h1-plaintext-http-control"),
            events.index("h1-plaintext-http-control-proof"),
        )
        self.assertLess(
            events.index("h1-plaintext-http-control-proof"),
            events.index("plaintext-http-control-phase-complete"),
        )

        target_header, target_body, target_url = self._plaintext_http_get(
            "mixedContentTargetUrl", origin=page_origin
        )
        self.assertEqual(target_url.port, control_url.port)
        self.assertIn("HTTP/1.1 200", target_header)
        self.assertIn(
            f"Access-Control-Allow-Origin: {page_origin}", target_header
        )
        self.assertIn(
            "X-M5-Mixed-Content-Target: reached", target_header
        )
        self.assertEqual(target_body, b"M5_MIXED_CONTENT_TARGET_UNEXPECTED")

        after_target = self._status()
        self.assertEqual(
            after_target["mixedContentTargetPostControlWispConnects"], 0
        )
        self.assertGreaterEqual(
            after_target["mixedContentTargetPostControlTcpConnections"], 1
        )
        self.assertEqual(
            after_target["mixedContentTargetPostControlRequests"], 1
        )
        target_events = [
            entry.get("event")
            for entry in after_target["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertIn(
            "mixed-content-target-post-control-tcp-connect", target_events
        )
        self.assertIn(
            "h1-mixed-content-target-post-control-request", target_events
        )

    def test_redirect_cookie_gate_rejects_then_allows_the_final_h2_page(
        self,
    ) -> None:
        evidence = self._exercise_redirect_cookie_gate()

        self.assertEqual(evidence["initialStatus"], 403)
        self.assertEqual(
            evidence["initialBody"], "M5_REDIRECT_COOKIE_REJECTED"
        )
        self.assertEqual(evidence["redirectStatus"], 302)
        self.assertEqual(evidence["redirectLocation"], "/m5/")
        self.assertEqual(evidence["cookieName"], "m5_redirect")
        self.assertEqual(evidence["wrongCookieStatus"], 403)
        self.assertEqual(
            evidence["wrongCookieBody"], "M5_REDIRECT_COOKIE_REJECTED"
        )
        self.assertEqual(
            evidence["cookieAttributes"],
            {
                "httpOnly": True,
                "pathM5": True,
                "sameSiteStrict": True,
                "secure": True,
            },
        )
        self.assertEqual(evidence["finalStatus"], 200)
        self.assertTrue(evidence["finalHasFixture"])
        expected_mixed_content_origin = (
            f"http://a.test:{urlsplit(self.metadata['plaintextHttpControlUrl']).port}"
        )
        self.assertIn(
            expected_mixed_content_origin,
            evidence["finalContentSecurityPolicy"],
        )
        self.assertEqual(
            evidence["finalContentSecurityPolicy"].count("http://"), 1
        )
        self.assertNotIn(
            "upgrade-insecure-requests", evidence["finalContentSecurityPolicy"]
        )
        self.assertNotIn(
            "block-all-mixed-content", evidence["finalContentSecurityPolicy"]
        )
        self.assertFalse(evidence["statusContainsCookie"])
        self.assertNotIn("m5_redirect=", json.dumps(evidence))

        status = self._status()
        self.assertEqual(status["redirectRequests"], 1)
        self.assertEqual(status["redirectCookieValidations"], 1)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(events.count("h2-page-cookie-rejected"), 2)
        self.assertLess(
            events.index("h2-redirect-cookie"),
            events.index("h2-page-cookie"),
        )

    def test_cache_revalidation_stores_then_returns_an_exact_304(self) -> None:
        evidence = self._exercise_cache_revalidation("exact")

        self.assertEqual(evidence["storeStatus"], 200)
        self.assertEqual(evidence["storeBody"], "M5_CACHE_REVALIDATE_OK")
        self.assertEqual(evidence["storeState"], "stored")
        self.assertEqual(evidence["etag"], '"m5-cache-revalidate-v1"')
        self.assertEqual(
            evidence["cacheControl"], "private, max-age=60, must-revalidate"
        )
        self.assertEqual(evidence["revalidateStatus"], 304)
        self.assertEqual(evidence["revalidateBody"], "")
        self.assertEqual(evidence["revalidateETag"], evidence["etag"])
        self.assertEqual(evidence["revalidateState"], "revalidated")
        self.assertFalse(evidence["revalidateHasContentLength"])

        status = self._status()
        self.assertEqual(status["cacheStore200s"], 1)
        self.assertEqual(status["cacheConditionalRequests"], 1)
        self.assertEqual(status["cacheNotModified304s"], 1)
        self.assertEqual(status["cacheUnexpectedRequests"], 0)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(events.count("h2-cache-store-200"), 1)
        self.assertEqual(events.count("h2-cache-revalidate-304"), 1)
        self.assertLess(
            events.index("h2-cache-store-200"),
            events.index("h2-cache-revalidate-304"),
        )

    def test_cache_revalidation_rejects_an_unexpected_validator(self) -> None:
        evidence = self._exercise_cache_revalidation("wrong")

        self.assertEqual(evidence["storeStatus"], 200)
        self.assertEqual(evidence["revalidateStatus"], 400)
        self.assertEqual(
            evidence["revalidateBody"], "M5_CACHE_REVALIDATE_UNEXPECTED"
        )

        status = self._status()
        self.assertEqual(status["cacheStore200s"], 1)
        self.assertEqual(status["cacheConditionalRequests"], 1)
        self.assertEqual(status["cacheNotModified304s"], 0)
        self.assertEqual(status["cacheUnexpectedRequests"], 1)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertIn("h2-cache-store-200", events)
        self.assertIn("h2-cache-revalidate-unexpected", events)
        self.assertNotIn("h2-cache-revalidate-304", events)

    def test_cache_revalidation_counters_are_bounded(self) -> None:
        evidence = self._exercise_cache_revalidation("saturate")
        self.assertEqual(evidence["statuses"], [200] * 20)

        status = self._status()
        self.assertEqual(status["cacheStore200s"], 16)
        self.assertEqual(status["cacheConditionalRequests"], 0)
        self.assertEqual(status["cacheNotModified304s"], 0)
        self.assertEqual(status["cacheUnexpectedRequests"], 0)

    def test_h2_cancel_stream_requires_an_exact_cancel_reset_before_proof(
        self,
    ) -> None:
        evidence = self._exercise_cancel_stream()

        self.assertEqual(evidence["responseStatus"], 200)
        self.assertEqual(evidence["firstChunk"], "M5_CANCEL_STREAM_FIRST_CHUNK")
        self.assertTrue(evidence["sentCancel"])
        self.assertEqual(evidence["proofStatus"], 200)
        self.assertEqual(evidence["proofBody"], "M5_CANCEL_STREAM_PROOF")

        status = self._status()
        self.assertEqual(status["cancelStreamPhase"], "cancel-observed")
        self.assertEqual(status["cancelStreamRequests"], 1)
        self.assertEqual(status["cancelStreamFirstChunks"], 1)
        self.assertEqual(status["cancelStreamCancelResets"], 1)
        self.assertEqual(status["cancelStreamUnexpectedResets"], 0)
        self.assertEqual(status["cancelStreamProofs"], 1)
        self.assertEqual(status["cancelStreamProofSessionMismatches"], 0)
        self.assertEqual(status["cancelStreamProofTimeouts"], 0)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(events.count("h2-cancel-stream-start"), 1)
        self.assertEqual(events.count("h2-cancel-stream-cancel-reset"), 1)
        self.assertEqual(events.count("h2-cancel-stream-proof"), 1)
        self.assertLess(
            events.index("h2-cancel-stream-start"),
            events.index("h2-cancel-stream-cancel-reset"),
        )
        self.assertLess(
            events.index("h2-cancel-stream-cancel-reset"),
            events.index("h2-cancel-stream-proof"),
        )

    def test_h2_cancel_stream_rejects_a_proof_from_another_session(self) -> None:
        evidence = self._exercise_cancel_stream_session_mismatch()

        self.assertEqual(evidence["firstChunk"], "M5_CANCEL_STREAM_FIRST_CHUNK")
        self.assertEqual(evidence["mismatchStatus"], 409)
        self.assertEqual(
            evidence["mismatchBody"], "M5_CANCEL_STREAM_PROOF_REJECTED"
        )
        self.assertEqual(evidence["proofStatus"], 200)
        self.assertEqual(evidence["proofBody"], "M5_CANCEL_STREAM_PROOF")

        status = self._status()
        self.assertEqual(status["cancelStreamPhase"], "cancel-observed")
        self.assertEqual(status["cancelStreamRequests"], 1)
        self.assertEqual(status["cancelStreamFirstChunks"], 1)
        self.assertEqual(status["cancelStreamCancelResets"], 1)
        self.assertEqual(status["cancelStreamUnexpectedResets"], 0)
        self.assertEqual(status["cancelStreamProofSessionMismatches"], 1)
        self.assertEqual(status["cancelStreamProofs"], 1)
        self.assertEqual(status["cancelStreamProofTimeouts"], 0)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(
            events.count("h2-cancel-stream-proof-session-mismatch"), 1
        )
        self.assertEqual(events.count("h2-cancel-stream-cancel-reset"), 1)
        self.assertEqual(events.count("h2-cancel-stream-proof"), 1)
        self.assertLess(
            events.index("h2-cancel-stream-proof-session-mismatch"),
            events.index("h2-cancel-stream-cancel-reset"),
        )

    def test_h2_slow_stream_requires_two_same_session_acks(self) -> None:
        evidence = self._exercise_slow_stream()

        self.assertEqual(evidence["responseStatus"], 200)
        self.assertEqual(evidence["firstStage"], "M5_SLOW_STREAM_FIRST_STAGE")
        self.assertEqual(
            evidence["firstAckBody"], "M5_SLOW_STREAM_FIRST_STAGE_ACK"
        )
        self.assertEqual(evidence["firstAckStatus"], 200)
        self.assertEqual(evidence["secondStage"], "M5_SLOW_STREAM_SECOND_STAGE")
        self.assertEqual(evidence["consumerPauseReadyStatus"], 200)
        self.assertEqual(
            evidence["consumerPauseReadyBody"],
            "M5_SLOW_STREAM_CONSUMER_PAUSE_READY",
        )
        self.assertGreaterEqual(evidence["consumerPauseElapsedMs"], 75)
        self.assertEqual(evidence["consumerBurstBytes"], 64 * 1024)
        self.assertTrue(evidence["consumerBurstAllExpectedBytes"])
        self.assertEqual(evidence["consumerResumeStatus"], 200)
        self.assertEqual(
            evidence["consumerResumeBody"], "M5_SLOW_STREAM_CONSUMER_RESUMED"
        )
        self.assertEqual(
            evidence["secondAckBody"], "M5_SLOW_STREAM_SECOND_STAGE_ACK"
        )
        self.assertEqual(evidence["secondAckStatus"], 200)
        self.assertEqual(evidence["thirdStage"], "M5_SLOW_STREAM_THIRD_STAGE")
        self.assertGreaterEqual(evidence["secondDelayMs"], 75)
        self.assertGreaterEqual(evidence["thirdDelayMs"], 75)
        self.assertEqual(evidence["proofStatus"], 200)
        self.assertEqual(evidence["proofBody"], "M5_SLOW_STREAM_PROOF")
        self.assertEqual(evidence["remainingBytes"], 0)

        status = self._status()
        self.assertEqual(status["slowStreamPhase"], "complete")
        for field in (
            "slowStreamRequests",
            "slowStreamFirstStages",
            "slowStreamSecondStages",
            "slowStreamThirdStages",
            "slowStreamCompletedStreams",
            "slowStreamConsumerBurstWrites",
            "slowStreamConsumerPauseReadyRequests",
            "slowStreamConsumerResumes",
            "slowStreamFirstStageAcks",
            "slowStreamSecondStageAcks",
            "slowStreamProofs",
            "slowStreamStageDelaySchedules",
        ):
            expected = 2 if field == "slowStreamStageDelaySchedules" else 1
            self.assertEqual(status[field], expected, field)
        self.assertEqual(status["slowStreamStageDelayMs"], 150)
        self.assertEqual(status["slowStreamConsumerBurstBytes"], 64 * 1024)
        self.assertEqual(status["slowStreamSessionMismatches"], 0)
        self.assertEqual(status["slowStreamStageAckTimeouts"], 0)
        self.assertEqual(status["slowStreamUnexpectedCloses"], 0)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        expected_events = (
            "h2-slow-stream-start",
            "h2-slow-stream-first-stage",
            "h2-slow-stream-first-stage-ack",
            "h2-slow-stream-second-stage",
            "h2-slow-stream-consumer-pause-ready",
            "h2-slow-stream-consumer-burst",
            "h2-slow-stream-consumer-resume",
            "h2-slow-stream-second-stage-ack",
            "h2-slow-stream-third-stage",
            "h2-slow-stream-complete",
            "h2-slow-stream-proof",
        )
        for event in expected_events:
            self.assertEqual(events.count(event), 1, event)
        self.assertEqual(
            [events.index(event) for event in expected_events],
            sorted(events.index(event) for event in expected_events),
        )
        burst_entry = next(
            entry
            for entry in status["transcript"]
            if entry.get("event") == "h2-slow-stream-consumer-burst"
        )
        self.assertTrue(burst_entry.get("backpressured"))

    def test_h2_slow_stream_rejects_first_ack_from_another_session(self) -> None:
        evidence = self._exercise_slow_stream(mismatch_mode="first-ack")

        self.assertEqual(evidence["mismatchStatus"], 409)
        self.assertEqual(evidence["mismatchBody"], "M5_SLOW_STREAM_REJECTED")
        self.assertEqual(evidence["firstAckStatus"], 200)
        self.assertEqual(evidence["secondAckStatus"], 200)
        self.assertEqual(evidence["proofStatus"], 200)
        self.assertEqual(evidence["proofBody"], "M5_SLOW_STREAM_PROOF")

        status = self._status()
        self.assertEqual(status["slowStreamPhase"], "complete")
        self.assertEqual(status["slowStreamSessionMismatches"], 1)
        self.assertEqual(status["slowStreamProofs"], 1)
        self.assertEqual(status["slowStreamUnexpectedCloses"], 0)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(
            events.count("h2-slow-stream-stage-ack-session-mismatch"), 1
        )
        self.assertLess(
            events.index("h2-slow-stream-stage-ack-session-mismatch"),
            events.index("h2-slow-stream-first-stage-ack"),
        )
        self.assertEqual(events.count("h2-slow-stream-proof"), 1)

    def test_h2_slow_stream_rejects_second_ack_from_another_session(self) -> None:
        evidence = self._exercise_slow_stream(mismatch_mode="second-ack")

        self.assertEqual(evidence["mismatchStatus"], 409)
        self.assertEqual(evidence["mismatchBody"], "M5_SLOW_STREAM_REJECTED")
        self.assertEqual(evidence["firstAckStatus"], 200)
        self.assertEqual(evidence["secondAckStatus"], 200)
        self.assertEqual(evidence["proofStatus"], 200)
        self.assertEqual(evidence["remainingBytes"], 0)

        status = self._status()
        self.assertEqual(status["slowStreamPhase"], "complete")
        self.assertEqual(status["slowStreamSessionMismatches"], 1)
        self.assertEqual(status["slowStreamProofs"], 1)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(
            events.count("h2-slow-stream-stage-ack-session-mismatch"), 1
        )
        self.assertLess(
            events.index("h2-slow-stream-stage-ack-session-mismatch"),
            events.index("h2-slow-stream-second-stage-ack"),
        )

    def test_h2_slow_stream_rejects_final_proof_from_another_session(self) -> None:
        evidence = self._exercise_slow_stream(mismatch_mode="proof")

        self.assertEqual(evidence["mismatchStatus"], 409)
        self.assertEqual(
            evidence["mismatchBody"], "M5_SLOW_STREAM_PROOF_REJECTED"
        )
        self.assertEqual(evidence["firstAckStatus"], 200)
        self.assertEqual(evidence["secondAckStatus"], 200)
        self.assertEqual(evidence["proofStatus"], 200)
        self.assertEqual(evidence["proofBody"], "M5_SLOW_STREAM_PROOF")
        self.assertEqual(evidence["remainingBytes"], 0)

        status = self._status()
        self.assertEqual(status["slowStreamPhase"], "complete")
        self.assertEqual(status["slowStreamSessionMismatches"], 1)
        self.assertEqual(status["slowStreamProofs"], 1)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(
            events.count("h2-slow-stream-proof-session-mismatch"), 1
        )
        self.assertLess(
            events.index("h2-slow-stream-proof-session-mismatch"),
            events.index("h2-slow-stream-proof"),
        )

    def test_h2_large_download_is_exact_and_bounded(self) -> None:
        evidence = self._exercise_large_download()

        self.assertEqual(evidence["responseStatus"], 200)
        self.assertEqual(evidence["contentLength"], str(512 * 1024))
        self.assertEqual(
            evidence["contentDisposition"],
            'attachment; filename="m5-large-download.bin"',
        )
        self.assertEqual(evidence["bytes"], 512 * 1024)
        self.assertGreaterEqual(evidence["chunks"], 1)
        self.assertTrue(evidence["exactBytes"])

        status = self._status()
        self.assertEqual(status["largeDownloadPhase"], "complete")
        self.assertEqual(status["largeDownloadRequests"], 1)
        self.assertEqual(status["largeDownloadCompletions"], 1)
        self.assertEqual(status["largeDownloadBytes"], 512 * 1024)
        self.assertEqual(status["largeDownloadChunks"], 32)
        self.assertGreaterEqual(status["largeDownloadBackpressureEvents"], 1)
        self.assertLessEqual(status["largeDownloadBackpressureEvents"], 32)
        self.assertEqual(status["largeDownloadUnexpectedCloses"], 0)
        events = [
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(events.count("h2-large-download-start"), 1)
        self.assertEqual(events.count("h2-large-download-complete"), 1)
        self.assertLess(
            events.index("h2-large-download-start"),
            events.index("h2-large-download-complete"),
        )

    def test_tls_failure_endpoint_is_trusted_but_rejects_a_test_name(self) -> None:
        parsed = urlsplit(self.metadata["tlsFailureUrl"])
        self.assertEqual(parsed.hostname, "a.test")
        self.assertIsNotNone(parsed.port)

        context = ssl.create_default_context(cafile=str(ROOT_CERTIFICATE))
        context.set_alpn_protocols(["h2"])
        raw = socket.create_connection(("127.0.0.1", parsed.port), timeout=5)
        try:
            with self.assertRaises(ssl.SSLCertVerificationError) as failure:
                context.wrap_socket(raw, server_hostname="a.test")
        finally:
            raw.close()

        # X509_V_ERR_HOSTNAME_MISMATCH is stable across the OpenSSL versions
        # used by Chromium's Python tooling. The chain is trusted; this is not
        # an authority, date, or transport failure.
        self.assertEqual(failure.exception.verify_code, 62)
        self.assertIn("Hostname mismatch", str(failure.exception))

        status = self._wait_for_tls_failure_tcp_connection()
        self.assertEqual(status["tlsMismatchHttpStreams"], 0)
        events = {
            entry.get("event")
            for entry in status["transcript"]
            if isinstance(entry, dict)
        }
        self.assertIn("tls-failure-tcp-connect", events)
        self.assertNotIn("tls-failure-http-request", events)

    def test_wisp_v21_fragmentation_ping_allowlist_and_transcript(self) -> None:
        control_header, _, _ = self._plaintext_http_get(
            "plaintextHttpControlUrl"
        )
        self.assertIn("HTTP/1.1 200", control_header)
        proof_header, proof_body, _ = self._plaintext_http_get(
            "plaintextHttpControlProofUrl"
        )
        self.assertIn("HTTP/1.1 200", proof_header)
        self.assertEqual(proof_body, b"M5_PLAINTEXT_CONTROL_PROOF")

        host, port, endpoint_path = self._endpoint("wispEndpoint")
        raw = socket.create_connection((host, port), timeout=5)
        self.addCleanup(raw.close)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        raw.sendall(
            f"GET {endpoint_path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Origin: http://127.0.0.1:8765\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: wisp\r\n\r\n".encode("ascii"))
        header, pending = read_http_headers(raw)
        self.assertIn("101 Switching Protocols", header)
        self.assertIn("Sec-WebSocket-Protocol: wisp", header)
        connection = BufferedSocket(raw, pending)

        finished, opcode, payload = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x02)
        packet_type, stream_id, info = parse_wisp_packet(payload)
        self.assertEqual((packet_type, stream_id), (0x05, 0))
        self.assertEqual(info, bytes([2, 1, 0x05, 0, 0, 0, 0]))

        # Fragment the client INFO acknowledgement and interleave a ping. The
        # relay must reassemble the message, reject no frame merely because it
        # is fragmented, and return a matching pong.
        client_info = wisp_packet(0x05, 0, bytes([2, 1, 0x05, 0, 0, 0, 0]))
        send_websocket_frame(raw, 0x02, client_info[:4], finished=False)
        send_websocket_frame(raw, 0x09, b"m5-ping")
        send_websocket_frame(raw, 0x00, client_info[4:])

        observed = []
        while len(observed) < 2:
            finished, opcode, payload = read_websocket_frame(connection)
            self.assertTrue(finished)
            observed.append((opcode, payload))
        self.assertIn((0x0A, b"m5-ping"), observed)
        continuation = next(payload for opcode, payload in observed if opcode == 0x02)
        packet_type, stream_id, credit = parse_wisp_packet(continuation)
        self.assertEqual((packet_type, stream_id), (0x03, 0))
        self.assertEqual(struct.unpack("<I", credit)[0], 1024)

        h2_port = urlsplit(self.metadata["httpsUrl"]).port
        assert h2_port is not None
        allowed = bytes([0x01]) + struct.pack("<H", h2_port) + b"a.test"
        send_websocket_frame(raw, 0x02, wisp_packet(0x01, 7, allowed))
        finished, opcode, payload = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x02)
        packet_type, stream_id, credit = parse_wisp_packet(payload)
        self.assertEqual((packet_type, stream_id), (0x03, 7))
        self.assertEqual(struct.unpack("<I", credit)[0], 64)

        plaintext_control_port = urlsplit(
            self.metadata["plaintextHttpControlUrl"]
        ).port
        assert plaintext_control_port is not None
        plaintext_control = (
            bytes([0x01]) +
            struct.pack("<H", plaintext_control_port) +
            b"a.test"
        )
        send_websocket_frame(
            raw, 0x02, wisp_packet(0x01, 11, plaintext_control)
        )
        finished, opcode, payload = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x02)
        packet_type, stream_id, credit = parse_wisp_packet(payload)
        self.assertEqual((packet_type, stream_id), (0x03, 11))
        self.assertEqual(struct.unpack("<I", credit)[0], 64)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self._status()
            if (
                status["mixedContentTargetPostControlWispConnects"] >= 1
                and status["mixedContentTargetPostControlTcpConnections"] >= 1
            ):
                break
            time.sleep(0.05)
        else:
            self.fail(
                "post-control plaintext listener did not observe WISP/TCP"
            )
        self.assertIn(
            {"hostname": "a.test", "port": plaintext_control_port},
            status["requestedDestinations"],
        )
        self.assertEqual(
            status["mixedContentTargetPostControlRequests"], 0
        )

        denied = bytes([0x01]) + struct.pack("<H", h2_port) + b"outside.test"
        send_websocket_frame(raw, 0x02, wisp_packet(0x01, 8, denied))
        finished, opcode, payload = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x02)
        packet_type, stream_id, reason = parse_wisp_packet(payload)
        self.assertEqual((packet_type, stream_id, reason), (0x04, 8, b"H"))

        udp = bytes([0x02]) + struct.pack("<H", h2_port) + b"a.test"
        send_websocket_frame(raw, 0x02, wisp_packet(0x01, 9, udp))
        finished, opcode, payload = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x02)
        packet_type, stream_id, reason = parse_wisp_packet(payload)
        self.assertEqual((packet_type, stream_id, reason), (0x04, 9, b"H"))

        tls_failure_port = urlsplit(self.metadata["tlsFailureUrl"]).port
        assert tls_failure_port is not None
        tls_failure = (
            bytes([0x01]) + struct.pack("<H", tls_failure_port) + b"a.test"
        )
        send_websocket_frame(raw, 0x02, wisp_packet(0x01, 10, tls_failure))
        finished, opcode, payload = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x02)
        packet_type, stream_id, credit = parse_wisp_packet(payload)
        self.assertEqual((packet_type, stream_id), (0x03, 10))
        self.assertEqual(struct.unpack("<I", credit)[0], 64)

        # The relay confirms the WISP stream before the loopback target has
        # necessarily accepted TCP. Wait for the target-side evidence while
        # the stream is still open so this test is independent of test order.
        status = self._wait_for_tls_failure_tcp_connection()
        self.assertIn(
            {"hostname": "a.test", "port": tls_failure_port},
            status["requestedDestinations"])
        self.assertEqual(status["tlsMismatchHttpStreams"], 0)

        send_websocket_frame(raw, 0x08, struct.pack("!H", 1000))
        finished, opcode, _ = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x08)

        status = self._status()
        self.assertGreaterEqual(status["wispSessions"], 1)
        self.assertIn(
            {"hostname": "a.test", "port": h2_port},
            status["requestedDestinations"])
        self.assertIn(
            {"hostname": "a.test", "port": plaintext_control_port},
            status["requestedDestinations"])
        self.assertGreaterEqual(
            status["mixedContentTargetPostControlWispConnects"], 1
        )
        self.assertGreaterEqual(
            status["mixedContentTargetPostControlTcpConnections"], 1
        )
        self.assertEqual(
            status["mixedContentTargetPostControlRequests"], 0
        )
        self.assertGreaterEqual(status["tlsMismatchTcpConnections"], 1)
        self.assertEqual(status["tlsMismatchHttpStreams"], 0)
        self.assertGreaterEqual(status["rejectedDestinations"], 2)
        self.assertEqual(status["udpPackets"], 1)
        self.assertEqual(status["relayErrors"], 0)


if __name__ == "__main__":
    unittest.main()

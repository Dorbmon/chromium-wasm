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

    def _status(self) -> dict[str, object]:
        with urlopen(self.metadata["transcriptUrl"], timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

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
        self.assertEqual(status["relayErrors"], 0)
        self.assertNotIn("PRIVATE KEY", json.dumps(status))

    def test_wisp_v21_fragmentation_ping_allowlist_and_transcript(self) -> None:
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

        send_websocket_frame(raw, 0x08, struct.pack("!H", 1000))
        finished, opcode, _ = read_websocket_frame(connection)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x08)

        status = self._status()
        self.assertGreaterEqual(status["wispSessions"], 1)
        self.assertIn(
            {"hostname": "a.test", "port": h2_port},
            status["requestedDestinations"])
        self.assertGreaterEqual(status["rejectedDestinations"], 2)
        self.assertEqual(status["udpPackets"], 1)
        self.assertEqual(status["relayErrors"], 0)


if __name__ == "__main__":
    unittest.main()

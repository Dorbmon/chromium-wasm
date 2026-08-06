#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wire-level contract tests for the separate public M5 WISP gateway.

The test-only raw-TCP hook maps one syntactically public, allowlisted logical
port-443 hostname to an ephemeral loopback echo listener. The production
gateway has no such configuration option: it always invokes node:net for the
allowlisted hostname and port 443 after the destination gate has accepted it.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY = ROOT_DIR / "tools/wasm/m5_public_wisp_gateway.js"
PINNED_NODE = ROOT_DIR / "third_party/emsdk/node/22.16.0_64bit/bin/node"
APPROVED_HOST = "relay-target.example.com"
LOOPBACK_UNAVAILABLE_MARKERS = ("EACCES", "EADDRINUSE", "EPERM")

WISP_CONNECT = 0x01
WISP_DATA = 0x02
WISP_CONTINUE = 0x03
WISP_CLOSE = 0x04
WISP_INFO = 0x05
WISP_BLOCKED = 0x48


def node_executable() -> str | None:
    if PINNED_NODE.is_file():
        return str(PINNED_NODE)
    return shutil.which("node")


def recv_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        if not chunk:
            raise AssertionError("unexpected end of stream")
        result.extend(chunk)
    return bytes(result)


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


def read_http_headers(connection: socket.socket) -> tuple[str, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            return "", bytes(data)
        data.extend(chunk)
        if len(data) > 64 * 1024:
            raise AssertionError("HTTP response headers are too large")
    header, pending = bytes(data).split(b"\r\n\r\n", 1)
    return header.decode("latin-1"), pending


def read_websocket_frame(connection: BufferedSocket) -> tuple[bool, int, bytes]:
    first, second = connection.read_exact(2)
    finished = bool(first & 0x80)
    opcode = first & 0x0F
    if first & 0x70 or second & 0x80:
        raise AssertionError("gateway emitted an invalid server WebSocket frame")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", connection.read_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", connection.read_exact(8))[0]
    if length > 64 * 1024 + 5:
        raise AssertionError("gateway emitted an oversized WebSocket frame")
    return finished, opcode, connection.read_exact(length)


def send_websocket_frame(
    connection: socket.socket, opcode: int, payload: bytes, *, finished: bool = True
) -> None:
    first = opcode | (0x80 if finished else 0)
    if len(payload) <= 125:
        header = bytes([first, 0x80 | len(payload)])
    elif len(payload) <= 0xFFFF:
        header = bytes([first, 0x80 | 126]) + struct.pack("!H", len(payload))
    else:
        header = bytes([first, 0x80 | 127]) + struct.pack("!Q", len(payload))
    mask = os.urandom(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    connection.sendall(header + mask + masked)


def wisp_packet(packet_type: int, stream_id: int, payload: bytes = b"") -> bytes:
    return bytes([packet_type]) + struct.pack("<I", stream_id) + payload


def parse_wisp_packet(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 5:
        raise AssertionError("WISP packet is shorter than its fixed header")
    return payload[0], struct.unpack("<I", payload[1:5])[0], payload[5:]


HARNESS = r"""
import net from "node:net";
import {pathToFileURL} from "node:url";

const gatewayPath = process.env.M5_PUBLIC_GATEWAY_PATH;
const configPath = process.env.M5_PUBLIC_GATEWAY_CONFIG_PATH;
if (!gatewayPath || !configPath) {
  throw new Error("missing test gateway paths");
}
const gatewayModule = await import(pathToFileURL(gatewayPath).href);
const config = gatewayModule.loadExternalPublicWispGatewayConfig(configPath);
let connectAttempts = 0;
let targetConnections = 0;
const target = net.createServer((socket) => {
  targetConnections += 1;
  socket.pipe(socket);
});
await new Promise((resolve, reject) => {
  target.once("error", reject);
  target.listen({host: "127.0.0.1", port: 0, exclusive: true}, resolve);
});
const targetAddress = target.address();
if (!targetAddress || typeof targetAddress === "string" ||
    targetAddress.address !== "127.0.0.1") {
  throw new Error("test echo listener did not bind loopback");
}
const {gateway, host, path, port} = await gatewayModule.startPublicWispGateway(
    config, {
      connectForTesting(hostname, destinationPort) {
        connectAttempts += 1;
        if (hostname !== "relay-target.example.com" || destinationPort !== 443) {
          throw new Error("unexpected test raw TCP destination");
        }
        return net.connect({
          allowHalfOpen: false,
          host: "127.0.0.1",
          port: targetAddress.port,
        });
      },
    });
process.stdout.write(`${JSON.stringify({host, path, port, schema_version: 1})}\n`);
let stopping = false;
async function stop() {
  if (stopping) {
    return;
  }
  stopping = true;
  await gateway.close();
  await new Promise((resolve) => target.close(() => resolve()));
  process.stdout.write(`${JSON.stringify({
    connect_attempts: connectAttempts,
    event: "stopped",
    target_connections: targetConnections,
  })}\n`);
}
process.stdin.setEncoding("utf8");
process.stdin.resume();
process.stdin.on("data", (data) => {
  if (String(data).split(/\r?\n/).includes("shutdown")) {
    void stop();
  }
});
process.stdin.on("end", () => {});
process.once("SIGINT", () => void stop());
process.once("SIGTERM", () => void stop());
"""


class M5PublicWispGatewayTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        node = node_executable()
        if node is None:
            self.skipTest("Node is unavailable")
        self.node = node
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-public-wisp-gateway-"
        )
        self.process: subprocess.Popen[str] | None = None
        self.shutdown_summary: dict[str, object] | None = None

    def tearDown(self) -> None:
        self._stop_gateway()
        self.temporary_directory.cleanup()

    def _start_gateway(self, *, max_sessions: int = 8) -> dict[str, object]:
        if self.process is not None:
            self.fail("gateway is already running")
        config_path = Path(self.temporary_directory.name) / "gateway.json"
        config_path.write_text(
            json.dumps(
                {
                    "approved_hosts": [APPROVED_HOST],
                    "limits": {"max_sessions": max_sessions},
                    "listen_port": 0,
                    "schema_version": 1,
                }
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["NODE_ENV"] = "test"
        environment["M5_PUBLIC_GATEWAY_PATH"] = str(GATEWAY)
        environment["M5_PUBLIC_GATEWAY_CONFIG_PATH"] = str(config_path)
        self.process = subprocess.Popen(
            [
                self.node,
                "--input-type=module",
                "-e",
                HARNESS,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
        )
        assert self.process.stdout is not None
        first_line = self.process.stdout.readline().strip()
        if not first_line:
            process = self.process
            self.process = None
            stdout, stderr = process.communicate(timeout=10)
            if any(marker in stderr for marker in LOOPBACK_UNAVAILABLE_MARKERS):
                self.skipTest("loopback TCP listeners are unavailable")
            self.fail(
                "gateway harness did not publish metadata: "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        metadata = json.loads(first_line)
        self.assertEqual(metadata["host"], "127.0.0.1")
        self.assertEqual(metadata["path"], "/wisp/")
        self.assertEqual(metadata["schema_version"], 1)
        self.assertIsInstance(metadata["port"], int)
        return metadata

    def _stop_gateway(self) -> dict[str, object] | None:
        process = self.process
        if process is None:
            return self.shutdown_summary
        self.process = None
        if process.poll() is None:
            assert process.stdin is not None
            process.stdin.write("shutdown\n")
            process.stdin.flush()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
        else:
            stdout, stderr = process.communicate(timeout=10)
        if process.returncode != 0:
            self.fail(
                "gateway harness terminated unexpectedly: "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            self.fail(f"gateway harness omitted shutdown summary: {stderr}")
        self.shutdown_summary = json.loads(lines[-1])
        self.assertEqual(self.shutdown_summary["event"], "stopped")
        return self.shutdown_summary

    def _open_raw(self, port: int) -> socket.socket:
        connection = socket.create_connection(("127.0.0.1", port), timeout=5)
        connection.settimeout(5)
        return connection

    def _upgrade(
        self,
        port: int,
        *,
        origin: str = "http://127.0.0.1:8765",
        path: str = "/wisp/",
        subprotocol: str | None = "wisp",
    ) -> tuple[BufferedSocket, str]:
        connection = self._open_raw(port)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Connection: Upgrade\r\n"
            "Upgrade: websocket\r\n"
            f"Origin: {origin}\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
        )
        if subprotocol is not None:
            request += f"Sec-WebSocket-Protocol: {subprotocol}\r\n"
        try:
            connection.sendall((request + "\r\n").encode("ascii"))
            header, pending = read_http_headers(connection)
            return BufferedSocket(connection, pending), header
        except Exception:
            connection.close()
            raise

    def _open_ready_wisp(self, port: int) -> BufferedSocket:
        client, header = self._upgrade(port)
        self.assertTrue(header.startswith("HTTP/1.1 101"), header)
        self.assertIn("Sec-WebSocket-Protocol: wisp", header)
        finished, opcode, payload = read_websocket_frame(client)
        self.assertTrue(finished)
        self.assertEqual(opcode, 0x02)
        self.assertEqual(
            parse_wisp_packet(payload),
            (WISP_INFO, 0, bytes([2, 1, 0x05, 0, 0, 0, 0])),
        )
        send_websocket_frame(
            client.connection,
            0x02,
            wisp_packet(WISP_INFO, 0, bytes([2, 1, 0x05, 0, 0, 0, 0])),
        )
        self.assertEqual(
            self._read_wisp_packet(client),
            (WISP_CONTINUE, 0, struct.pack("<I", 1024)),
        )
        return client

    def _read_wisp_packet(self, client: BufferedSocket) -> tuple[int, int, bytes]:
        while True:
            finished, opcode, payload = read_websocket_frame(client)
            self.assertTrue(finished)
            if opcode == 0x09:
                send_websocket_frame(client.connection, 0x0A, payload)
                continue
            self.assertEqual(opcode, 0x02)
            return parse_wisp_packet(payload)

    def _connect_stream(
        self, client: BufferedSocket, stream_id: int, hostname: str, port: int
    ) -> tuple[int, int, bytes]:
        destination = bytes([0x01]) + struct.pack("<H", port) + hostname.encode(
            "ascii"
        )
        send_websocket_frame(
            client.connection, 0x02, wisp_packet(WISP_CONNECT, stream_id, destination)
        )
        return self._read_wisp_packet(client)

    def _close_client(self, client: BufferedSocket) -> None:
        try:
            send_websocket_frame(client.connection, 0x08, struct.pack("!H", 1000))
            read_websocket_frame(client)
        except (AssertionError, OSError, TimeoutError):
            pass
        finally:
            client.connection.close()

    def test_v21_handshake_443_raw_tcp_forwarding_and_credit_replenishment(
        self,
    ) -> None:
        metadata = self._start_gateway()
        client = self._open_ready_wisp(int(metadata["port"]))
        try:
            self.assertEqual(
                self._connect_stream(client, 7, APPROVED_HOST, 443),
                (WISP_CONTINUE, 7, struct.pack("<I", 64)),
            )
            # 65 packets proves the gateway refreshes the absolute WISP
            # stream credit after crossing the initial 64-packet grant.
            available_credit = 64
            for value in range(65):
                self.assertGreater(available_credit, 0)
                body = bytes([value])
                send_websocket_frame(
                    client.connection, 0x02, wisp_packet(WISP_DATA, 7, body)
                )
                available_credit -= 1
                received_data = False
                received_credit = False
                for _ in range(8):
                    packet_type, stream_id, payload = self._read_wisp_packet(client)
                    if packet_type == WISP_DATA and stream_id == 7:
                        self.assertEqual(payload, body)
                        received_data = True
                    elif packet_type == WISP_CONTINUE and stream_id == 7:
                        self.assertEqual(payload, struct.pack("<I", 64))
                        available_credit = 64
                        received_credit = True
                    else:
                        self.fail(
                            "unexpected WISP packet while checking raw TCP forwarding: "
                            f"{packet_type}/{stream_id}"
                        )
                    if received_data and received_credit:
                        break
                self.assertTrue(received_data)
                self.assertTrue(received_credit)
        finally:
            self._close_client(client)
        summary = self._stop_gateway()
        assert summary is not None
        self.assertEqual(summary["connect_attempts"], 1)
        self.assertEqual(summary["target_connections"], 1)

    def test_same_approved_host_port_444_is_blocked_before_connect(self) -> None:
        metadata = self._start_gateway()
        client = self._open_ready_wisp(int(metadata["port"]))
        try:
            self.assertEqual(
                self._connect_stream(client, 8, APPROVED_HOST, 444),
                (WISP_CLOSE, 8, bytes([WISP_BLOCKED])),
            )
        finally:
            self._close_client(client)
        summary = self._stop_gateway()
        assert summary is not None
        self.assertEqual(summary["connect_attempts"], 0)
        self.assertEqual(summary["target_connections"], 0)

    def test_unapproved_host_is_blocked_before_connect(self) -> None:
        metadata = self._start_gateway()
        client = self._open_ready_wisp(int(metadata["port"]))
        try:
            self.assertEqual(
                self._connect_stream(client, 9, "unapproved-target.example.com", 443),
                (WISP_CLOSE, 9, bytes([WISP_BLOCKED])),
            )
        finally:
            self._close_client(client)
        summary = self._stop_gateway()
        assert summary is not None
        self.assertEqual(summary["connect_attempts"], 0)
        self.assertEqual(summary["target_connections"], 0)

    def test_invalid_origin_subprotocol_and_path_are_rejected(self) -> None:
        metadata = self._start_gateway()
        port = int(metadata["port"])
        rejected = [
            self._upgrade(port, origin="http://localhost:8765"),
            self._upgrade(port, subprotocol="not-wisp"),
            self._upgrade(port, path="/not-wisp/"),
            self._upgrade(port, subprotocol="wisp, unrelated"),
        ]
        for client, header in rejected:
            try:
                self.assertFalse(header.startswith("HTTP/1.1 101"), header)
            finally:
                client.connection.close()
        summary = self._stop_gateway()
        assert summary is not None
        self.assertEqual(summary["connect_attempts"], 0)
        self.assertEqual(summary["target_connections"], 0)

    def test_connection_cap_releases_after_carrier_close(self) -> None:
        metadata = self._start_gateway(max_sessions=1)
        first = self._open_ready_wisp(int(metadata["port"]))
        try:
            try:
                blocked, header = self._upgrade(int(metadata["port"]))
            except OSError:
                # server.maxConnections may reset the second raw connection
                # before Node's HTTP parser reaches the upgrade handler.
                pass
            else:
                try:
                    self.assertFalse(header.startswith("HTTP/1.1 101"), header)
                finally:
                    blocked.connection.close()
        finally:
            self._close_client(first)
        deadline = time.monotonic() + 5
        while True:
            try:
                replacement = self._open_ready_wisp(int(metadata["port"]))
                break
            except (AssertionError, OSError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        self._close_client(replacement)

    def test_cli_shutdown_releases_its_stdin_watcher(self) -> None:
        config_path = Path(self.temporary_directory.name) / "cli-gateway.json"
        config_path.write_text(
            json.dumps(
                {
                    "approved_hosts": [APPROVED_HOST],
                    "listen_port": 0,
                    "schema_version": 1,
                }
            ),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [self.node, str(GATEWAY), "--config", str(config_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        metadata = process.stdout.readline().strip()
        if not metadata:
            stdout, stderr = process.communicate(timeout=10)
            if "loopback listener unavailable" in stderr:
                self.skipTest("loopback listener is unavailable in this sandbox")
            self.fail(
                "gateway CLI did not publish metadata: "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        self.assertEqual(json.loads(metadata)["listen_origin"].split(":", 1)[0], "http")
        process.stdin.write("shutdown\n")
        process.stdin.flush()
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertIn('{"event":"stopped"}', stdout.splitlines())

    def test_configuration_accepts_only_public_allowlist_fields(self) -> None:
        program = r"""
import assert from "node:assert/strict";
import {pathToFileURL} from "node:url";

const gatewayPath = process.env.M5_PUBLIC_GATEWAY_PATH;
const gateway = await import(pathToFileURL(gatewayPath).href);
const base = {
  approved_hosts: ["relay-target.example.com"],
  schema_version: 1,
};
assert.deepEqual(
    gateway.validatePublicWispGatewayConfig(base).approvedHosts,
    ["relay-target.example.com"]);
assert.equal(
    gateway.normalizePublicDnsHostname("RELAY-TARGET.EXAMPLE.COM"),
    "relay-target.example.com");
for (const invalidHost of ["127.0.0.1", "localhost", "target.test"]) {
  assert.throws(() => gateway.validatePublicWispGatewayConfig({
    ...base,
    approved_hosts: [invalidHost],
  }));
}
for (const forbiddenField of ["endpoint", "proxy", "token"]) {
  assert.throws(() => gateway.validatePublicWispGatewayConfig({
    ...base,
    [forbiddenField]: "not-configurable",
  }));
}
"""
        environment = os.environ.copy()
        environment["M5_PUBLIC_GATEWAY_PATH"] = str(GATEWAY)
        result = subprocess.run(
            [self.node, "--input-type=module", "-e", program],
            capture_output=True,
            env=environment,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()

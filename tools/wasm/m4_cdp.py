#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Small dependency-free DevTools client for the M4 host-input smoke."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import time
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from m0_common import M0Error


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _read_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise M0Error("DevTools WebSocket closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class DevToolsClient:
    def __init__(self, websocket_url: str):
        parsed = urlsplit(websocket_url)
        if parsed.scheme != "ws" or not parsed.hostname or not parsed.port:
            raise M0Error("DevTools returned an invalid loopback WebSocket URL")
        self._connection = socket.create_connection(
            (parsed.hostname, parsed.port), timeout=10
        )
        self._connection.settimeout(10)
        request_path = parsed.path or "/"
        if parsed.query:
            request_path += f"?{parsed.query}"
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = "\r\n".join(
            (
                f"GET {request_path} HTTP/1.1",
                f"Host: {parsed.hostname}:{parsed.port}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
                "Origin: http://localhost",
                "",
                "",
            )
        ).encode("ascii")
        self._connection.sendall(handshake)
        response = self._read_headers()
        if not response.startswith(b"HTTP/1.1 101 "):
            raise M0Error("DevTools rejected the WebSocket handshake")
        expected_accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        if (
            f"sec-websocket-accept: {expected_accept}"
            .encode("ascii")
            .lower()
            not in response.lower()
        ):
            raise M0Error("DevTools returned an invalid WebSocket handshake")
        self._next_id = 0

    def _read_headers(self) -> bytes:
        received = bytearray()
        while b"\r\n\r\n" not in received:
            received.extend(_read_exact(self._connection, 1))
            if len(received) > 16384:
                raise M0Error("DevTools WebSocket headers are too large")
        return bytes(received)

    def close(self) -> None:
        try:
            self._connection.close()
        except OSError:
            pass

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        if len(payload) < 126:
            header.append(0x80 | len(payload))
        elif len(payload) <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(len(payload).to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(len(payload).to_bytes(8, "big"))
        masked = bytes(
            value ^ mask[index % 4] for index, value in enumerate(payload)
        )
        self._connection.sendall(bytes(header) + mask + masked)

    def _send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def _receive(self) -> dict[str, Any]:
        first, second = _read_exact(self._connection, 2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(_read_exact(self._connection, 2), "big")
        elif length == 127:
            length = int.from_bytes(_read_exact(self._connection, 8), "big")
        if length > 16 * 1024 * 1024:
            raise M0Error("DevTools WebSocket frame is too large")
        mask = _read_exact(self._connection, 4) if masked else None
        payload = _read_exact(self._connection, length)
        if mask is not None:
            payload = bytes(
                value ^ mask[index % 4] for index, value in enumerate(payload)
            )
        if opcode == 0x8:
            raise M0Error("DevTools WebSocket closed")
        if opcode == 0x9:
            self._send_frame(0xA, payload)
            return self._receive()
        if opcode != 0x1 or not (first & 0x80):
            raise M0Error("DevTools returned an unsupported WebSocket frame")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise M0Error("DevTools returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise M0Error("DevTools returned a non-object message")
        return value

    def call(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._next_id += 1
        message: dict[str, Any] = {"id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send_text(json.dumps(message, separators=(",", ":")))
        while True:
            response = self._receive()
            if response.get("id") != self._next_id:
                continue
            if "error" in response:
                raise M0Error(f"DevTools {method} failed: {response['error']!r}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise M0Error(f"DevTools {method} returned an invalid result")
            return result

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        remote = result.get("result")
        if not isinstance(remote, dict):
            raise M0Error("DevTools Runtime.evaluate returned no value")
        if remote.get("subtype") == "error" or "exceptionDetails" in result:
            raise M0Error(f"DevTools evaluation failed: {result!r}")
        return remote.get("value")

    def dispatch_primary_click(self, x: float, y: float) -> None:
        base = {"x": x, "y": y, "button": "left", "pointerType": "mouse"}
        self.call("Input.dispatchMouseEvent", {**base, "type": "mouseMoved"})
        self.call(
            "Input.dispatchMouseEvent",
            {**base, "type": "mousePressed", "clickCount": 1},
        )
        self.call(
            "Input.dispatchMouseEvent",
            {**base, "type": "mouseReleased", "clickCount": 1},
        )

    def dispatch_primary_drag(
        self,
        start_x: float,
        start_y: float,
        middle_x: float,
        middle_y: float,
        end_x: float,
        end_y: float,
    ) -> None:
        """Drive one physical primary-button drag without text input.

        Each movement remains an ordinary DevTools mouse event.  The two
        held-button moves deliberately make the drag path observable through
        the host's captured pointer route rather than treating the end point
        as a click or using a DOM selection command.
        """

        start = {
            "x": start_x,
            "y": start_y,
            "button": "left",
            "pointerType": "mouse",
        }
        self.call("Input.dispatchMouseEvent", {**start, "type": "mouseMoved"})
        self.call(
            "Input.dispatchMouseEvent",
            {**start, "type": "mousePressed", "clickCount": 1},
        )
        for x, y in ((middle_x, middle_y), (end_x, end_y)):
            self.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "buttons": 1,
                    "pointerType": "mouse",
                },
            )
        self.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": end_x,
                "y": end_y,
                "button": "left",
                "clickCount": 1,
                "pointerType": "mouse",
            },
        )

    def dispatch_mouse_wheel(
        self,
        x: float,
        y: float,
        delta_x: float,
        delta_y: float,
    ) -> None:
        self.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": x,
                "y": y,
                "deltaX": delta_x,
                "deltaY": delta_y,
                "pointerType": "mouse",
            },
        )

    def dispatch_arrow_down_down(self) -> None:
        base = {
            "code": "ArrowDown",
            "key": "ArrowDown",
            "windowsVirtualKeyCode": 40,
            "modifiers": 0,
        }
        self.call(
            "Input.dispatchKeyEvent",
            {
                **base,
                "type": "rawKeyDown",
            },
        )

    def dispatch_arrow_down(self) -> None:
        self.dispatch_arrow_down_down()
        base = {
            "code": "ArrowDown",
            "key": "ArrowDown",
            "windowsVirtualKeyCode": 40,
            "modifiers": 0,
        }
        self.call(
            "Input.dispatchKeyEvent",
            {
                **base,
                "type": "keyUp",
            },
        )

    def dispatch_key_a(self) -> None:
        base = {
            "code": "KeyA",
            "key": "a",
            "windowsVirtualKeyCode": 65,
            "modifiers": 0,
        }
        self.call(
            "Input.dispatchKeyEvent",
            {
                **base,
                "type": "rawKeyDown",
            },
        )
        self.call(
            "Input.dispatchKeyEvent",
            {
                **base,
                "type": "keyUp",
            },
        )

    def dispatch_backspace(self) -> None:
        """Drive one physical Backspace key pair without a text payload."""

        base = {
            "code": "Backspace",
            "key": "Backspace",
            "windowsVirtualKeyCode": 8,
            "modifiers": 0,
        }
        self.call(
            "Input.dispatchKeyEvent",
            {
                **base,
                "type": "rawKeyDown",
            },
        )
        self.call(
            "Input.dispatchKeyEvent",
            {
                **base,
                "type": "keyUp",
            },
        )

    def dispatch_ime_preedit(self) -> None:
        """Drive one outer host textarea composition candidate."""

        self.call(
            "Input.imeSetComposition",
            {
                "text": "🙂",
                "selectionStart": 2,
                "selectionEnd": 2,
                "replacementStart": 0,
                "replacementEnd": 0,
            },
        )

    def dispatch_ime_commit(self) -> None:
        """Commit the active outer candidate through Chrome's IME API."""

        self.call("Input.insertText", {"text": "🙂"})

    def dispatch_ime_cancel(self) -> None:
        """Cancel the active outer candidate through Chrome's IME API."""

        self.call(
            "Input.imeSetComposition",
            {
                "text": "",
                "selectionStart": 0,
                "selectionEnd": 0,
                "replacementStart": 0,
                "replacementEnd": 0,
            },
        )


def wait_for_page_client(
    port: int, expected_url_prefix: str, deadline: float
) -> DevToolsClient:
    endpoint = f"http://127.0.0.1:{port}/json/list"
    last_error = "DevTools endpoint did not become ready"
    while time.monotonic() < deadline:
        try:
            with urlopen(endpoint, timeout=1) as response:
                targets = json.loads(response.read().decode("utf-8"))
            if not isinstance(targets, list):
                raise M0Error("DevTools target listing is invalid")
            for target in targets:
                if (
                    isinstance(target, dict)
                    and target.get("type") == "page"
                    and isinstance(target.get("url"), str)
                    and target["url"].startswith(expected_url_prefix)
                    and isinstance(target.get("webSocketDebuggerUrl"), str)
                ):
                    return DevToolsClient(target["webSocketDebuggerUrl"])
            last_error = "M4 host page is not listed by DevTools"
        except (OSError, ValueError, M0Error) as exc:
            last_error = str(exc)
        time.sleep(0.05)
    raise M0Error(last_error)

#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import secrets
import sys
import threading
from typing import Any
from urllib.parse import urlencode, urlsplit

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    fail,
    load_manifest,
    print_context,
)


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".map": "application/json",
    ".wasm": "application/wasm",
}


@dataclass
class ServerState:
    token: str
    out_dir: Path
    result_queue: queue.Queue[dict[str, Any]]
    verbose: bool = False
    result_received: bool = False
    result_lock: threading.Lock = field(default_factory=threading.Lock)


class M0RequestHandler(BaseHTTPRequestHandler):
    server_version = "ChromiumWasmM0/1"

    @property
    def state(self) -> ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, format_string: str, *args: object) -> None:
        if self.state.verbose:
            super().log_message(format_string, *args)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path in ("/", "/__smoke__/hello"):
            host_page = Path(__file__).with_name("host") / "hello.html"
            self._send_bytes(
                host_page.read_bytes(), CONTENT_TYPES[host_page.suffix]
            )
            return

        allowed_artifacts = {
            f"/out/wasm/{name}": self.state.out_dir / name
            for name in (
                "hello_wasm.js",
                "hello_wasm.wasm",
                "hello_wasm.wasm.map",
            )
        }
        artifact = allowed_artifacts.get(request_path)
        if artifact is None or not artifact.is_file():
            self.send_error(404)
            return
        self._send_bytes(
            artifact.read_bytes(),
            CONTENT_TYPES.get(artifact.suffix, "application/octet-stream"),
        )

    def do_POST(self) -> None:
        request_path = urlsplit(self.path).path
        expected_path = f"/__smoke__/result/{self.state.token}"
        if request_path != expected_path:
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length <= 0 or length > 1024 * 1024:
            self.send_error(413)
            return
        try:
            result = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return
        if not isinstance(result, dict) or result.get("protocol") != 1:
            self.send_error(400)
            return

        with self.state.result_lock:
            if self.state.result_received:
                self.send_error(409)
                return
            self.state.result_received = True
            self.state.result_queue.put_nowait(result)
        self._send_bytes(b'{"accepted":true}\n', "application/json")


class M0HTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        state: ServerState,
    ) -> None:
        self.state = state
        super().__init__(address, M0RequestHandler)


def create_server(
    bind: str,
    port: int,
    out_dir: Path,
    token: str,
    result_queue: queue.Queue[dict[str, Any]],
    *,
    verbose: bool = False,
) -> M0HTTPServer:
    resolved_out_dir = out_dir.resolve()
    if not (resolved_out_dir / "hello_wasm.js").is_file():
        raise M0Error("hello_wasm.js is missing from the output directory")
    if not (resolved_out_dir / "hello_wasm.wasm").is_file():
        raise M0Error("hello_wasm.wasm is missing from the output directory")
    state = ServerState(
        token=token,
        out_dir=resolved_out_dir,
        result_queue=result_queue,
        verbose=verbose,
    )
    return M0HTTPServer((bind, port), state)


def smoke_url(
    server: M0HTTPServer,
    token: str,
    manifest: dict[str, Any],
    port_commit: str,
    timeout_seconds: float = 20.0,
) -> str:
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "chromium": manifest["chromium"]["revision"],
            "emscripten": manifest["emscripten"]["source_revision"],
            "module": "/out/wasm/hello_wasm.js",
            "port": port_commit,
            "token": token,
            "timeout_ms": max(
                1000, min(120000, int(timeout_seconds * 1000))
            ),
            "v8": manifest["git_dependencies"]["v8"]["revision"],
        }
    )
    return f"http://{host}:{port}/__smoke__/hello?{query}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve the M0 host page with cross-origin isolation headers."
    )
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--out-dir", type=Path, default=Path("out/wasm"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        token = secrets.token_urlsafe(24)
        results: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        out_dir = args.out_dir
        if not out_dir.is_absolute():
            out_dir = REPO_ROOT / out_dir
        server = create_server(
            args.bind,
            args.port,
            out_dir,
            token,
            results,
            verbose=args.verbose,
        )
        port_commit = checked_output(["git", "rev-parse", "HEAD"])
        print_context(
            "serve.py",
            manifest,
            bind=args.bind,
            port=server.server_address[1],
        )
        print(
            "CHROMIUM_WASM_M0:SERVE " +
            smoke_url(server, token, manifest, port_commit),
            flush=True,
        )
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())

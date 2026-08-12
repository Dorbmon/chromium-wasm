#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Check the pre-release package's static serving contract.

This deliberately does not claim a Chrome UI, profile, compatibility, or M9
stress pass. It proves that the bounded package tree can be served with the
required cross-origin isolation headers and exact MIME types before an external
release server is selected.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

if __package__:
    from .m0_common import M0Error
    from .package import (
        PACKAGE_PATHS,
        REQUIRED_HEADERS,
        REQUIRED_MIME_TYPES,
        SENTINEL,
        verify_release_tree,
    )
else:
    from m0_common import M0Error
    from package import (
        PACKAGE_PATHS,
        REQUIRED_HEADERS,
        REQUIRED_MIME_TYPES,
        SENTINEL,
        verify_release_tree,
    )


class PackageSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], dist_dir: Path):
        self.dist_dir = dist_dir
        super().__init__(address, PackageSmokeRequestHandler)


class PackageSmokeRequestHandler(BaseHTTPRequestHandler):
    server: PackageSmokeServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def end_headers(self) -> None:
        for name, value in REQUIRED_HEADERS.items():
            self.send_header(name, value)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._serve()

    def do_HEAD(self) -> None:
        self._serve()

    def _serve(self) -> None:
        status, content_type, contents = package_response(
            self.server.dist_dir, urlsplit(self.path).path
        )
        if status != HTTPStatus.OK:
            self._send_bytes(
                status, content_type, contents
            )
            return
        self._send_bytes(HTTPStatus.OK, content_type, contents)


def create_package_smoke_server(
    bind: str, port: int, dist_dir: Path
) -> PackageSmokeServer:
    verify_release_tree(dist_dir)
    return PackageSmokeServer((bind, port), dist_dir.resolve())


def package_response(
    dist_dir: Path, request_path: str
) -> tuple[HTTPStatus, str, bytes]:
    """Return one safe static-package response without opening a socket."""
    if request_path in ("", "/"):
        artifact = "index.html"
    else:
        artifact = request_path.removeprefix("/")
    if artifact not in PACKAGE_PATHS:
        return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
    path = dist_dir.resolve() / artifact
    try:
        contents = path.read_bytes()
    except OSError:
        return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
    return (
        HTTPStatus.OK,
        REQUIRED_MIME_TYPES.get(path.suffix, "text/plain; charset=utf-8"),
        contents,
    )


def run_package_smoke(dist_dir: Path) -> dict[str, object]:
    verification = verify_release_tree(dist_dir)
    server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
    thread = threading.Thread(
        target=server.serve_forever,
        name="chromium-wasm-m9-package-server",
        daemon=True,
    )
    thread.start()
    try:
        host, port = server.server_address[:2]
        observed: dict[str, dict[str, object]] = {}
        requested = {
            "/": "text/html; charset=utf-8",
            "/chromium-wasm.js": "text/javascript; charset=utf-8",
            "/chromium-wasm.wasm": "application/wasm",
            "/VERSION.json": "application/json; charset=utf-8",
        }
        for path, expected_mime in requested.items():
            with urlopen(f"http://{host}:{port}{path}", timeout=10) as response:
                body = response.read()
                if response.status != HTTPStatus.OK:
                    raise M0Error(f"package endpoint returned {response.status}: {path}")
                if response.headers.get_content_type() != expected_mime.split(";", 1)[0]:
                    raise M0Error(f"package endpoint MIME mismatch: {path}")
                if not body:
                    raise M0Error(f"package endpoint is empty: {path}")
                for header, expected in REQUIRED_HEADERS.items():
                    if response.headers.get(header) != expected:
                        raise M0Error(
                            f"package endpoint header mismatch: {path} {header}"
                        )
                observed[path] = {
                    "bytes": len(body),
                    "content_type": response.headers.get("Content-Type"),
                }
        version = json.loads((dist_dir.resolve() / "VERSION.json").read_text("utf-8"))
        if version.get("release_status") != "pre_m7_m8_not_releasable":
            raise M0Error("package smoke accepted a non-pre-release status")
        return {
            "endpoints": observed,
            "release_status": verification["release_status"],
            "scope": "static-package-headers-mime-and-artifact-integrity-only",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the static pre-release Chromium Wasm package smoke."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_package_smoke(args.dist_dir)
        print(
            f"{SENTINEL}:SMOKE_PASS "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    except (M0Error, OSError, TypeError, ValueError) as exc:
        print(f"{SENTINEL}:SMOKE_FAIL reason={exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

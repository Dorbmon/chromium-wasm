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
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import threading
from types import MappingProxyType
from typing import Callable, Mapping
from urllib.parse import urlsplit
from urllib.request import urlopen

if __package__:
    from .m0_common import M0Error
    from .m9_server_cleanup import shutdown_server_bounded
    from .package import (
        MAX_ARTIFACT_BYTES,
        PACKAGE_PATHS,
        REQUIRED_HEADERS,
        REQUIRED_MIME_TYPES,
        SENTINEL,
        verify_release_snapshot,
    )
else:
    from m0_common import M0Error
    from m9_server_cleanup import shutdown_server_bounded
    from package import (
        MAX_ARTIFACT_BYTES,
        PACKAGE_PATHS,
        REQUIRED_HEADERS,
        REQUIRED_MIME_TYPES,
        SENTINEL,
        verify_release_snapshot,
    )


@dataclass(frozen=True)
class PackageTreeSnapshot:
    """The fixed package bytes and verification record served by one server."""

    artifacts: Mapping[str, bytes]
    verification: Mapping[str, object]


class PackageSmokeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], snapshot: PackageTreeSnapshot):
        self.snapshot = snapshot
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
            self.server.snapshot.artifacts, urlsplit(self.path).path
        )
        if status != HTTPStatus.OK:
            self._send_bytes(
                status, content_type, contents
            )
            return
        self._send_bytes(HTTPStatus.OK, content_type, contents)


ArtifactIdentity = tuple[int, int, int, int, int, int]
_SNAPSHOT_READ_CHUNK_BYTES = 1024 * 1024


def _identity(metadata: os.stat_result) -> ArtifactIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _required_open_flag(name: str) -> int:
    """Get one nonzero host flag required for safe descriptor capture."""

    try:
        value = getattr(os, name)
    except AttributeError as exc:
        raise M0Error(f"package snapshot requires host {name} support") from exc
    if type(value) is not int or value == 0:
        raise M0Error(f"package snapshot requires host {name} support")
    return value


def _no_follow_open_flags(*, directory: bool) -> int:
    """Return host flags that fail closed when a path component is a link."""

    flags = os.O_RDONLY | _required_open_flag("O_NOFOLLOW")
    if directory:
        return flags | _required_open_flag("O_DIRECTORY") | getattr(
            os, "O_CLOEXEC", 0
        )
    # An attacker can replace a regular artifact with a FIFO or device
    # between verification and open. O_NONBLOCK lets fstat reject that
    # descriptor rather than waiting for an untrusted producer.
    return flags | _required_open_flag("O_NONBLOCK") | getattr(os, "O_CLOEXEC", 0)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _directory_identity(fd: int, description: str) -> ArtifactIdentity:
    try:
        metadata = os.fstat(fd)
    except OSError as exc:
        raise M0Error(f"package snapshot {description} cannot be inspected") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise M0Error(f"package snapshot {description} is not a directory")
    return _identity(metadata)


def _artifact_identity_from_fd(fd: int, description: str) -> ArtifactIdentity:
    try:
        metadata = os.fstat(fd)
    except OSError as exc:
        raise M0Error(f"package snapshot {description} cannot be inspected") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise M0Error(f"package snapshot {description} is not a regular file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_ARTIFACT_BYTES:
        raise M0Error(f"package snapshot {description} size is invalid")
    return _identity(metadata)


def _open_directory_at(parent_fd: int, component: str, description: str) -> int:
    try:
        fd = os.open(
            component,
            _no_follow_open_flags(directory=True),
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise M0Error(
            f"package snapshot {description} cannot be opened safely"
        ) from exc
    try:
        _directory_identity(fd, description)
    except BaseException:
        _close_quietly(fd)
        raise
    return fd


def _open_artifact_at(parent_fd: int, component: str, description: str) -> int:
    try:
        fd = os.open(
            component,
            _no_follow_open_flags(directory=False),
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise M0Error(
            f"package snapshot {description} cannot be opened safely"
        ) from exc
    try:
        _artifact_identity_from_fd(fd, description)
    except BaseException:
        _close_quietly(fd)
        raise
    return fd


def _absolute_snapshot_root(dist_dir: Path) -> Path:
    """Make a lexical absolute root without resolving any supplied links."""

    root = Path(dist_dir)
    if any(component == ".." for component in root.parts):
        raise M0Error("package snapshot root has an unsafe path component")
    if not root.is_absolute():
        try:
            root = Path(os.getcwd()) / root
        except OSError as exc:
            raise M0Error("package snapshot root cannot be made absolute") from exc
    if not root.is_absolute() or not root.anchor:
        raise M0Error("package snapshot root is not an absolute directory")
    return root


def _open_snapshot_root(root: Path) -> int:
    """Open every absolute package-root component without following a link."""

    if not root.is_absolute() or not root.anchor:
        raise M0Error("package snapshot root is not an absolute directory")
    try:
        fd = os.open(str(Path(root.anchor)), _no_follow_open_flags(directory=True))
    except OSError as exc:
        raise M0Error("package snapshot root cannot be opened safely") from exc
    try:
        _directory_identity(fd, "root anchor")
        for component in root.parts[1:]:
            if component in ("", ".", ".."):
                raise M0Error("package snapshot root has an unsafe path component")
            next_fd = _open_directory_at(fd, component, "root directory")
            _close_quietly(fd)
            fd = next_fd
        return fd
    except BaseException:
        _close_quietly(fd)
        raise


def _package_path_parts(relative: str) -> tuple[str, ...]:
    if relative not in PACKAGE_PATHS:
        raise M0Error(f"package snapshot artifact path is invalid: {relative}")
    parts = tuple(relative.split("/"))
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise M0Error(f"package snapshot artifact path is invalid: {relative}")
    return parts


def _open_snapshot_artifact(root_fd: int, relative: str, description: str) -> int:
    """Open one known package artifact beneath a trusted root descriptor."""

    try:
        parent_fd = os.dup(root_fd)
    except OSError as exc:
        raise M0Error(
            f"package snapshot {description} cannot be opened safely"
        ) from exc
    try:
        parts = _package_path_parts(relative)
        for component in parts[:-1]:
            next_fd = _open_directory_at(parent_fd, component, description)
            _close_quietly(parent_fd)
            parent_fd = next_fd
        return _open_artifact_at(parent_fd, parts[-1], description)
    finally:
        _close_quietly(parent_fd)


def _read_exact_artifact_bytes(
    fd: int, expected_size: int, description: str
) -> bytes:
    """Read exactly the fstat size plus at most one trailing-byte probe."""

    remaining = expected_size
    chunks: list[bytes] = []
    while remaining:
        try:
            chunk = os.read(fd, min(_SNAPSHOT_READ_CHUNK_BYTES, remaining))
        except OSError as exc:
            raise M0Error(f"package snapshot {description} cannot be read") from exc
        if not chunk:
            raise M0Error(f"package snapshot {description} changed while it was read")
        chunks.append(chunk)
        remaining -= len(chunk)
    try:
        trailing = os.read(fd, 1)
    except OSError as exc:
        raise M0Error(f"package snapshot {description} cannot be read") from exc
    if trailing:
        raise M0Error(f"package snapshot {description} changed while it was read")
    return b"".join(chunks)


def _read_snapshot_file(
    root_fd: int, relative: str, description: str
) -> tuple[bytes, ArtifactIdentity]:
    """Copy one descriptor-pinned file while rejecting in-place changes."""

    fd = _open_snapshot_artifact(root_fd, relative, description)
    try:
        before = _artifact_identity_from_fd(fd, description)
        contents = _read_exact_artifact_bytes(fd, before[3], description)
        after = _artifact_identity_from_fd(fd, description)
        if before != after or len(contents) != before[3]:
            raise M0Error(f"package snapshot {description} changed while it was read")
        return contents, before
    finally:
        _close_quietly(fd)


def _current_artifact_identity(
    root_fd: int, relative: str, description: str
) -> ArtifactIdentity:
    fd = _open_snapshot_artifact(root_fd, relative, description)
    try:
        return _artifact_identity_from_fd(fd, description)
    finally:
        _close_quietly(fd)


def snapshot_package_tree(dist_dir: Path) -> PackageTreeSnapshot:
    """Verify then capture one immutable, coherent package tree.

    The smoke server must not re-read build output after it begins serving.
    Capture every allowed file through a descriptor-pinned no-follow path and
    require every captured identity to remain unchanged across the capture
    window. Validate only the resulting in-memory bytes, including the full
    canonical VERSION.json schema and every manifest artifact hash. This never
    observes an untrusted package path before or after descriptor capture.
    """

    root = _absolute_snapshot_root(dist_dir)
    names = tuple(sorted(PACKAGE_PATHS))
    root_fd = _open_snapshot_root(root)
    try:
        before = _directory_identity(root_fd, "root directory")
        captures = {
            name: _read_snapshot_file(root_fd, name, f"artifact {name}")
            for name in names
        }
        artifacts = {name: capture[0] for name, capture in captures.items()}
        identities = {name: capture[1] for name, capture in captures.items()}
        after = _directory_identity(root_fd, "root directory")
        current = {
            name: _current_artifact_identity(root_fd, name, f"artifact {name}")
            for name in names
        }
    finally:
        _close_quietly(root_fd)
    if before != after or identities != current:
        raise M0Error("package changed while it was snapshotted")
    try:
        verification = verify_release_snapshot(artifacts)
    except M0Error:
        raise
    except (TypeError, ValueError) as exc:
        raise M0Error(f"package snapshot validation failed: {exc}") from exc
    return PackageTreeSnapshot(
        artifacts=MappingProxyType(artifacts),
        verification=MappingProxyType(dict(verification)),
    )


def create_package_smoke_server(
    bind: str, port: int, dist_dir: Path
) -> PackageSmokeServer:
    return PackageSmokeServer((bind, port), snapshot_package_tree(dist_dir))


def package_response(
    artifacts: Mapping[str, bytes], request_path: str
) -> tuple[HTTPStatus, str, bytes]:
    """Return one response from a fixed, verified in-memory package snapshot."""
    if request_path in ("", "/"):
        artifact = "index.html"
    else:
        artifact = request_path.removeprefix("/")
    if artifact not in PACKAGE_PATHS:
        return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
    contents = artifacts.get(artifact)
    if contents is None:
        return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n"
    if type(contents) is not bytes or not contents:
        raise M0Error(f"package snapshot artifact is invalid: {artifact}")
    return (
        HTTPStatus.OK,
        REQUIRED_MIME_TYPES.get(Path(artifact).suffix, "text/plain; charset=utf-8"),
        contents,
    )


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    """Run one cleanup action without preventing remaining cleanup."""

    try:
        action()
    except BaseException as exc:
        if cleanup_error is None:
            return exc
    return cleanup_error


def _join_package_smoke_server(thread: threading.Thread) -> None:
    thread.join(timeout=5)
    if thread.is_alive():
        raise M0Error("package smoke server did not stop")


def run_package_smoke(dist_dir: Path) -> dict[str, object]:
    server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
    verification = server.snapshot.verification
    thread: threading.Thread | None = None
    thread_started = False
    primary_error: BaseException | None = None
    try:
        thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-package-server",
            daemon=True,
        )
        thread.start()
        thread_started = True
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
                    raise M0Error(
                        f"package endpoint returned {response.status}: {path}"
                    )
                if (
                    response.headers.get_content_type()
                    != expected_mime.split(";", 1)[0]
                ):
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
        release_status = verification.get("release_status")
        if release_status != "pre_m7_m8_not_releasable":
            raise M0Error("package smoke accepted a non-pre-release status")
        return {
            "endpoints": observed,
            "release_status": release_status,
            "scope": "static-package-headers-mime-and-artifact-integrity-only",
        }
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        if thread_started:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: shutdown_server_bounded(
                    server, timeout=5, description="M9 package smoke server"
                ),
            )
        cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
        if thread_started and thread is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: _join_package_smoke_server(thread)
            )
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


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

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
import http.client
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import stat
import threading
from types import MappingProxyType
from typing import Callable, Mapping
from urllib.parse import urlsplit

if __package__:
    from .m0_common import M0Error
    from .m9_server_cleanup import (
        M9TrackingThreadingHTTPServer,
        shutdown_server_bounded,
    )
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
    from m9_server_cleanup import (
        M9TrackingThreadingHTTPServer,
        shutdown_server_bounded,
    )
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


@dataclass(frozen=True)
class PackageEndpointResponse:
    """One fully captured loopback response from the immutable package tree."""

    status: int
    headers: Mapping[str, str | None]
    body: bytes


NOT_FOUND_PATH = "/__chromium_wasm_package_not_found__"
NOT_FOUND_CONTENT_TYPE = "text/plain; charset=utf-8"
NOT_FOUND_BODY = b"not found\n"
PACKAGE_SMOKE_TIMEOUT_SECONDS = 10.0
_DELIVERY_HEADER_NAMES = frozenset(
    (*REQUIRED_HEADERS, "Cache-Control", "Content-Length", "Content-Type")
)
# The fixed three-document reload observation needs a server-side request
# receipt that is unambiguously tied to one document lifetime.  This is an
# opt-in test-server namespace only: normal package URLs and the immutable
# package bytes remain unchanged.
EPOCH_ROUTE_PREFIX = "/__chromium_wasm_m9_epoch__/"
EPOCH_QUERY_KEY = "m9_package_epoch"
MAX_EPOCH_ROUTE_COUNT = 3
MAX_EPOCH_SUCCESSFUL_GETS = 32


class PackageSmokeServer(M9TrackingThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], snapshot: PackageTreeSnapshot):
        self.snapshot = snapshot
        self._epoch_route_lock = threading.Lock()
        self._epoch_route_successful_gets: dict[str, list[str]] = {}
        self._epoch_route_receipt_overflow: set[str] = set()
        super().__init__(address, PackageSmokeRequestHandler)

    @staticmethod
    def _is_valid_epoch_route_token(value: object) -> bool:
        return (
            isinstance(value, str)
            and 1 <= len(value) <= 96
            and value.isascii()
            and all(character.isalnum() or character in "-_" for character in value)
        )

    def register_epoch_route(self, epoch: str) -> str:
        """Enable one opaque same-origin path namespace for a test epoch.

        The caller supplies the same random token in the outer-document query
        and path.  The handler accepts only registered tokens, so a generic
        static package request cannot accidentally become an epoch receipt.
        """

        if not self._is_valid_epoch_route_token(epoch):
            raise M0Error("package epoch route token is invalid")
        with self._epoch_route_lock:
            if epoch in self._epoch_route_successful_gets:
                raise M0Error("package epoch route token was reused")
            if len(self._epoch_route_successful_gets) >= MAX_EPOCH_ROUTE_COUNT:
                raise M0Error("package epoch route count exceeds its bound")
            self._epoch_route_successful_gets[epoch] = []
        return f"{EPOCH_ROUTE_PREFIX}{epoch}/"

    def resolve_epoch_scoped_request_path(
        self, request_path: str
    ) -> tuple[str | None, str | None]:
        """Map a registered virtual epoch path to one canonical package path.

        A ``None`` package path means that the request was unsafe or addressed
        an unregistered epoch and must receive the ordinary fixed 404 response.
        Unscoped paths are returned verbatim, preserving the root static-server
        delivery contract.
        """

        if not isinstance(request_path, str):
            return None, None
        if not request_path.startswith(EPOCH_ROUTE_PREFIX):
            return None, request_path
        remaining = request_path.removeprefix(EPOCH_ROUTE_PREFIX)
        epoch, separator, artifact = remaining.partition("/")
        if (
            not separator
            or not self._is_valid_epoch_route_token(epoch)
            or artifact.startswith("/")
            or "%" in artifact
        ):
            return None, None
        if artifact and any(
            component in ("", ".", "..") for component in artifact.split("/")
        ):
            return None, None
        with self._epoch_route_lock:
            if epoch not in self._epoch_route_successful_gets:
                return None, None
        return epoch, "/" if not artifact else f"/{artifact}"

    def resolve_epoch_scoped_request_target(
        self, request_target: str
    ) -> tuple[str | None, str | None]:
        """Resolve one origin-form request target and its epoch receipt.

        Epoch routes exist solely to bind one fresh outer document to the
        corresponding server-side receipt. Require its exact opaque token in
        both the virtual path and document query. Artifact requests under the
        route are queryless, so they cannot be substituted for the document
        receipt or introduce an unobserved variant.
        """

        if not isinstance(request_target, str):
            return None, None
        try:
            parsed = urlsplit(request_target)
        except (TypeError, ValueError):
            return None, None
        if (
            parsed.scheme
            or parsed.netloc
            or request_target.startswith("//")
            or "#" in request_target
            or not parsed.path.startswith("/")
        ):
            return None, None
        epoch, package_path = self.resolve_epoch_scoped_request_path(parsed.path)
        if epoch is None:
            return epoch, package_path
        if package_path == "/":
            if parsed.query != f"{EPOCH_QUERY_KEY}={epoch}":
                return None, None
        elif parsed.query or "?" in request_target:
            return None, None
        return epoch, package_path

    def record_epoch_successful_get(self, epoch: str, package_path: str) -> None:
        """Retain one bounded, successful GET fact for a registered epoch."""

        with self._epoch_route_lock:
            requests = self._epoch_route_successful_gets.get(epoch)
            if requests is None:
                return
            if len(requests) >= MAX_EPOCH_SUCCESSFUL_GETS:
                self._epoch_route_receipt_overflow.add(epoch)
                return
            requests.append(package_path)

    def epoch_successful_get_counts(self, epoch: str) -> dict[str, int]:
        """Copy the bounded server-side successful-GET receipt for one epoch."""

        if not self._is_valid_epoch_route_token(epoch):
            raise M0Error("package epoch route token is invalid")
        with self._epoch_route_lock:
            requests = self._epoch_route_successful_gets.get(epoch)
            if requests is None:
                raise M0Error("package epoch route is not registered")
            if epoch in self._epoch_route_receipt_overflow:
                raise M0Error("package epoch successful GET receipt exceeded its bound")
            counts: dict[str, int] = {}
            for package_path in requests:
                counts[package_path] = counts.get(package_path, 0) + 1
            return counts


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

    def _raw_request_target(self) -> str | None:
        """Return the unnormalized target accepted by the base parser."""

        try:
            words = self.raw_requestline.decode("iso-8859-1").rstrip("\r\n").split()
        except (AttributeError, UnicodeError):
            return None
        if len(words) not in (2, 3):
            return None
        return words[1]

    def _serve(self) -> None:
        request_target = self._raw_request_target()
        if request_target is None:
            epoch, package_path = None, None
        else:
            epoch, package_path = self.server.resolve_epoch_scoped_request_target(
                request_target
            )
        if package_path is None:
            status, content_type, contents = (
                HTTPStatus.NOT_FOUND,
                NOT_FOUND_CONTENT_TYPE,
                NOT_FOUND_BODY,
            )
        else:
            status, content_type, contents = package_response(
                self.server.snapshot.artifacts, package_path
            )
        self._send_bytes(status, content_type, contents)
        if (
            epoch is not None
            and status == HTTPStatus.OK
            and self.command == "GET"
        ):
            # A ready package host can only consume a response after this
            # handler has completed the body write.  The runner snapshots this
            # receipt after that readiness acknowledgement.
            self.server.record_epoch_successful_get(epoch, package_path)


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
        return HTTPStatus.NOT_FOUND, NOT_FOUND_CONTENT_TYPE, NOT_FOUND_BODY
    contents = artifacts.get(artifact)
    if contents is None:
        return HTTPStatus.NOT_FOUND, NOT_FOUND_CONTENT_TYPE, NOT_FOUND_BODY
    if type(contents) is not bytes or not contents:
        raise M0Error(f"package snapshot artifact is invalid: {artifact}")
    return (
        HTTPStatus.OK,
        REQUIRED_MIME_TYPES.get(Path(artifact).suffix, "text/plain; charset=utf-8"),
        contents,
    )


def _package_request_path(artifact: str) -> str:
    """Map the packaged index to its public root URL exactly once."""

    if artifact == "index.html":
        return "/"
    return f"/{artifact}"


def _expected_content_type(artifact: str) -> str:
    return REQUIRED_MIME_TYPES.get(
        Path(artifact).suffix, "text/plain; charset=utf-8"
    )


def _capture_endpoint_response(
    response: object, *, status: object
) -> PackageEndpointResponse:
    """Copy only the response facts needed for the static-delivery proof."""

    if type(status) is not int:
        raise M0Error("package endpoint returned an invalid HTTP status")
    try:
        response_headers = response.headers  # type: ignore[attr-defined]
        body = response.read()  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        raise M0Error("package endpoint response could not be captured") from exc
    if type(body) is not bytes:
        raise M0Error("package endpoint response body is invalid")
    try:
        header_values = {
            name: response_headers.get_all(name) for name in _DELIVERY_HEADER_NAMES
        }
    except (AttributeError, TypeError) as exc:
        raise M0Error("package endpoint response headers are invalid") from exc
    headers: dict[str, str | None] = {}
    for name, values in header_values.items():
        if values is None:
            headers[name] = None
            continue
        if (
            type(values) is not list
            or len(values) != 1
            or type(values[0]) is not str
        ):
            raise M0Error("package endpoint response headers are invalid")
        headers[name] = values[0]
    return PackageEndpointResponse(
        status=status,
        headers=MappingProxyType(headers),
        body=body,
    )


def _fetch_package_response(
    host: str, port: int, request_path: str, method: str
) -> PackageEndpointResponse:
    """Issue one direct no-cache GET or HEAD loopback request."""

    if method not in ("GET", "HEAD"):
        raise ValueError("package endpoint method is invalid")
    connection = http.client.HTTPConnection(
        host, port, timeout=PACKAGE_SMOKE_TIMEOUT_SECONDS
    )
    try:
        connection.request(method, request_path, headers={"Cache-Control": "no-store"})
        response = connection.getresponse()
        return _capture_endpoint_response(
            response, status=getattr(response, "status", None)
        )
    except (OSError, http.client.HTTPException) as exc:
        raise M0Error("package endpoint request failed") from exc
    finally:
        connection.close()


def _require_delivery_headers(
    response: PackageEndpointResponse,
    *,
    request_path: str,
    content_type: str,
    content_length: int,
) -> None:
    expected_headers = {
        **REQUIRED_HEADERS,
        "Cache-Control": "no-store",
        "Content-Length": str(content_length),
        "Content-Type": content_type,
    }
    for name, expected in expected_headers.items():
        if response.headers.get(name) != expected:
            raise M0Error(f"package endpoint header mismatch: {request_path} {name}")


def _verify_artifact_delivery_response(
    response: PackageEndpointResponse,
    *,
    artifact: str,
    request_path: str,
    method: str,
    expected_body: bytes,
) -> None:
    """Require one canonical response for a captured package artifact."""

    if response.status != HTTPStatus.OK:
        raise M0Error(f"package endpoint returned {response.status}: {request_path}")
    _require_delivery_headers(
        response,
        request_path=request_path,
        content_type=_expected_content_type(artifact),
        content_length=len(expected_body),
    )
    if method == "GET":
        if response.body != expected_body:
            raise M0Error(f"package endpoint bytes mismatch: {request_path}")
        return
    if method == "HEAD":
        if response.body:
            raise M0Error(f"package endpoint HEAD body is not empty: {request_path}")
        return
    raise ValueError("package endpoint method is invalid")


def _verify_not_found_delivery_response(
    response: PackageEndpointResponse,
    *,
    artifacts: Mapping[str, bytes],
    method: str,
) -> None:
    """Require a fixed 404 that cannot echo a staged artifact."""

    if response.status != HTTPStatus.NOT_FOUND:
        raise M0Error(
            f"package not-found endpoint returned {response.status}: {NOT_FOUND_PATH}"
        )
    _require_delivery_headers(
        response,
        request_path=NOT_FOUND_PATH,
        content_type=NOT_FOUND_CONTENT_TYPE,
        content_length=len(NOT_FOUND_BODY),
    )
    if method == "GET":
        if any(response.body == artifact for artifact in artifacts.values()):
            raise M0Error("package not-found endpoint leaked a staged artifact")
        if response.body != NOT_FOUND_BODY:
            raise M0Error("package not-found endpoint body is not safe")
        return
    if method == "HEAD":
        if response.body:
            raise M0Error("package not-found endpoint HEAD body is not empty")
        return
    raise ValueError("package endpoint method is invalid")


def _verify_static_package_delivery(
    host: str, port: int, snapshot: PackageTreeSnapshot
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    """Exercise every public package path against its in-memory byte capture."""

    artifacts = snapshot.artifacts
    if set(artifacts) != PACKAGE_PATHS:
        raise M0Error("package snapshot artifact set is invalid")
    observed: dict[str, dict[str, object]] = {}
    for artifact in sorted(PACKAGE_PATHS, key=_package_request_path):
        expected_body = artifacts.get(artifact)
        if type(expected_body) is not bytes or not expected_body:
            raise M0Error(f"package snapshot artifact is invalid: {artifact}")
        request_path = _package_request_path(artifact)
        for method in ("GET", "HEAD"):
            _verify_artifact_delivery_response(
                _fetch_package_response(host, port, request_path, method),
                artifact=artifact,
                request_path=request_path,
                method=method,
                expected_body=expected_body,
            )
        observed[request_path] = {
            "artifact": artifact,
            "bytes": len(expected_body),
            "content_type": _expected_content_type(artifact),
            "methods": ["GET", "HEAD"],
        }

    if NOT_FOUND_PATH.removeprefix("/") in PACKAGE_PATHS:
        raise M0Error("package not-found probe collides with a staged artifact")
    for method in ("GET", "HEAD"):
        _verify_not_found_delivery_response(
            _fetch_package_response(host, port, NOT_FOUND_PATH, method),
            artifacts=artifacts,
            method=method,
        )
    return observed, {
        "path": NOT_FOUND_PATH,
        "bytes": len(NOT_FOUND_BODY),
        "content_type": NOT_FOUND_CONTENT_TYPE,
        "methods": ["GET", "HEAD"],
    }


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
        observed, not_found = _verify_static_package_delivery(
            host, port, server.snapshot
        )
        release_status = verification.get("release_status")
        if release_status != "pre_m7_m8_not_releasable":
            raise M0Error("package smoke accepted a non-pre-release status")
        return {
            "endpoints": observed,
            "not_found": not_found,
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
        cleanup_error = _run_cleanup_action(
            cleanup_error,
            lambda: server.join_request_handlers(
                timeout=5, description="M9 package smoke server"
            ),
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

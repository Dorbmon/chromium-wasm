#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Descriptor-pinned regular-file snapshots for bounded M9 browser evidence.

These helpers capture a fixed set of direct children of one trusted directory
or one independent regular file.  They deliberately do not establish build or
source provenance: callers retain their existing provenance language and use
the returned bytes as their immutable in-memory server inputs.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Iterable

if __package__:
    from .m0_common import M0Error
else:
    from m0_common import M0Error


_SnapshotIdentity = tuple[int, int, int, int, int, int]
_READ_CHUNK_BYTES = 1024 * 1024


def _required_open_flag(name: str, description: str) -> int:
    try:
        value = getattr(os, name)
    except AttributeError as exc:
        raise M0Error(f"{description} requires host {name} support") from exc
    if type(value) is not int or value == 0:
        raise M0Error(f"{description} requires host {name} support")
    return value


def _require_dir_fd_support(description: str) -> None:
    if os.open not in os.supports_dir_fd:
        raise M0Error(f"{description} requires host dir_fd support")


def _directory_open_flags(description: str) -> int:
    return (
        os.O_RDONLY
        | _required_open_flag("O_NOFOLLOW", description)
        | _required_open_flag("O_DIRECTORY", description)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_open_flags(description: str) -> int:
    # O_NONBLOCK keeps a substituted FIFO from making an evidence runner wait
    # for an untrusted writer before fstat can reject it as non-regular.
    return (
        os.O_RDONLY
        | _required_open_flag("O_NOFOLLOW", description)
        | _required_open_flag("O_NONBLOCK", description)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _identity(metadata: os.stat_result) -> _SnapshotIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(descriptor: int, description: str) -> _SnapshotIdentity:
    try:
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise M0Error(f"{description} cannot be inspected") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise M0Error(f"{description} is not a directory")
    return _identity(metadata)


def _regular_file_identity(
    descriptor: int, *, maximum_bytes: int, description: str
) -> _SnapshotIdentity:
    try:
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise M0Error(f"{description} cannot be inspected") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise M0Error(f"{description} must be a regular file")
    if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
        raise M0Error(f"{description} snapshot is invalid")
    return _identity(metadata)


def _lexical_absolute_path(path: Path, description: str) -> Path:
    try:
        candidate = Path(path)
    except (TypeError, ValueError) as exc:
        raise M0Error(f"{description} has an unsafe path component") from exc
    if "\0" in str(candidate):
        raise M0Error(f"{description} has an unsafe path component")
    if any(component == ".." for component in candidate.parts):
        raise M0Error(f"{description} has an unsafe path component")
    if not candidate.is_absolute():
        try:
            candidate = Path(os.getcwd()) / candidate
        except OSError as exc:
            raise M0Error(f"{description} cannot be made absolute") from exc
    if not candidate.is_absolute() or not candidate.anchor:
        raise M0Error(f"{description} is not an absolute path")
    return candidate


def _open_root_directory(path: Path, description: str) -> int:
    """Open every lexical path component without following a link."""

    _require_dir_fd_support(description)
    root = _lexical_absolute_path(path, description)
    descriptor = -1
    try:
        descriptor = os.open(
            str(Path(root.anchor)), _directory_open_flags(description)
        )
        _directory_identity(descriptor, description)
        for component in root.parts[1:]:
            if component in ("", ".", ".."):
                raise M0Error(f"{description} has an unsafe path component")
            next_descriptor = os.open(
                component,
                _directory_open_flags(description),
                dir_fd=descriptor,
            )
            try:
                _directory_identity(next_descriptor, description)
            except BaseException:
                _close_quietly(next_descriptor)
                raise
            _close_quietly(descriptor)
            descriptor = next_descriptor
        return descriptor
    except (OSError, TypeError, ValueError) as exc:
        _close_quietly(descriptor)
        raise M0Error(f"{description} cannot be opened safely") from exc
    except BaseException:
        _close_quietly(descriptor)
        raise


def _validate_names(names: Iterable[str], description: str) -> tuple[str, ...]:
    if isinstance(names, (str, bytes)):
        raise M0Error(f"{description} file names are invalid")
    try:
        names = tuple(names)
    except TypeError as exc:
        raise M0Error(f"{description} file names are invalid") from exc
    if not names:
        raise M0Error(f"{description} file names are invalid")
    for name in names:
        if (
            type(name) is not str
            or not name
            or name in (".", "..")
            or "/" in name
            or "\\" in name
            or "\0" in name
        ):
            raise M0Error(f"{description} file names are invalid")
    if len(set(names)) != len(names):
        raise M0Error(f"{description} file names are invalid")
    return names


def _open_regular_file_at(
    root_descriptor: int,
    name: str,
    *,
    maximum_bytes: int,
    description: str,
) -> int:
    try:
        descriptor = os.open(
            name,
            _file_open_flags(description),
            dir_fd=root_descriptor,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise M0Error(f"{description} cannot be opened safely") from exc
    try:
        _regular_file_identity(
            descriptor, maximum_bytes=maximum_bytes, description=description
        )
    except BaseException:
        _close_quietly(descriptor)
        raise
    return descriptor


def _read_exact_bytes(
    descriptor: int, *, expected_size: int, description: str
) -> bytes:
    remaining = expected_size
    chunks: list[bytes] = []
    while remaining:
        try:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
        except OSError as exc:
            raise M0Error(f"{description} cannot be read") from exc
        if not chunk:
            raise M0Error(f"{description} changed while it was read")
        chunks.append(chunk)
        remaining -= len(chunk)
    try:
        trailing = os.read(descriptor, 1)
    except OSError as exc:
        raise M0Error(f"{description} cannot be read") from exc
    if trailing:
        raise M0Error(f"{description} changed while it was read")
    return b"".join(chunks)


def _snapshot_file_from_root(
    root_descriptor: int,
    name: str,
    *,
    maximum_bytes: int,
    description: str,
) -> tuple[bytes, _SnapshotIdentity]:
    descriptor = _open_regular_file_at(
        root_descriptor,
        name,
        maximum_bytes=maximum_bytes,
        description=description,
    )
    try:
        before = _regular_file_identity(
            descriptor, maximum_bytes=maximum_bytes, description=description
        )
        contents = _read_exact_bytes(
            descriptor, expected_size=before[3], description=description
        )
        after = _regular_file_identity(
            descriptor, maximum_bytes=maximum_bytes, description=description
        )
    finally:
        _close_quietly(descriptor)
    if before != after or len(contents) != before[3]:
        raise M0Error(f"{description} changed while it was read")
    return contents, before


def _current_file_identity_from_root(
    root_descriptor: int,
    name: str,
    *,
    maximum_bytes: int,
    description: str,
) -> _SnapshotIdentity:
    descriptor = _open_regular_file_at(
        root_descriptor,
        name,
        maximum_bytes=maximum_bytes,
        description=description,
    )
    try:
        return _regular_file_identity(
            descriptor, maximum_bytes=maximum_bytes, description=description
        )
    finally:
        _close_quietly(descriptor)


def snapshot_regular_files(
    root: Path,
    names: Iterable[str],
    *,
    maximum_bytes: int,
    description: str,
) -> dict[str, bytes]:
    """Copy named direct-child files through one no-follow root descriptor.

    The selected leaf identities are re-opened from that same root descriptor
    after capture.  This deliberately does not compare directory timestamps:
    unrelated build-output or diagnostics changes must not invalidate the
    precise in-memory inputs that the server will own.
    """

    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise M0Error(f"{description} snapshot bound is invalid")
    selected_names = _validate_names(names, description)
    root_descriptor = _open_root_directory(root, description)
    try:
        captures = {
            name: _snapshot_file_from_root(
                root_descriptor,
                name,
                maximum_bytes=maximum_bytes,
                description=f"{description} {name}",
            )
            for name in selected_names
        }
        identities = {name: capture[1] for name, capture in captures.items()}
        current = {
            name: _current_file_identity_from_root(
                root_descriptor,
                name,
                maximum_bytes=maximum_bytes,
                description=f"{description} {name}",
            )
            for name in selected_names
        }
    finally:
        _close_quietly(root_descriptor)
    if identities != current:
        raise M0Error(f"{description} changed while snapshotting")
    return {name: capture[0] for name, capture in captures.items()}


def snapshot_regular_file(
    path: Path, *, maximum_bytes: int, description: str
) -> bytes:
    """Copy one independently selected file through its descriptor-pinned parent."""

    absolute_path = _lexical_absolute_path(path, description)
    name = absolute_path.name
    if not name:
        raise M0Error(f"{description} file name is invalid")
    return snapshot_regular_files(
        absolute_path.parent,
        (name,),
        maximum_bytes=maximum_bytes,
        description=description,
    )[name]

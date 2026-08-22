#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Observe descriptor-pinned Chrome Wasm artifact sizes for later M9 work.

This runner reads the fixed ``chrome_wasm`` loader and Wasm module, and binds
the adjacent generated ``args.gn`` by byte identity.  It reports the module
pair's immutable-at-capture raw byte identities and a local gzip sample whose
header has an empty filename and zero timestamp.  The gzip sample is an
encoding observation under the recorded Python/zlib implementation; it is not
a generated distribution artifact, HTTP content encoding, or network transfer
measurement.

The result intentionally remains non-release evidence.  It does not build,
stage, launch, serve, benchmark, or assess the unresolved M7/M8 gates.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import zlib

if __package__:
    from .m0_common import M0Error, REPO_ROOT
    from .m9_descriptor_snapshot import RegularFileHash, hash_regular_files
else:
    from m0_common import M0Error, REPO_ROOT
    from m9_descriptor_snapshot import RegularFileHash, hash_regular_files


SENTINEL = "CHROMIUM_WASM_M9_ARTIFACT_SIZE_INVENTORY"
OBSERVED_PREFIX = f"{SENTINEL}:OBSERVED "
SCHEMA_VERSION = 1
CASE = "chrome_wasm_m9_artifact_size_inventory"
SCOPE = "descriptor-pinned-raw-module-size-and-local-gzip-observation-only"
STATUS = "observed_nonrelease_size_inventory"
RELEASE_STATUS = "pre_m7_m8_not_releasable"
EXPECTED_GATE_STATE = {
    "persistent_profile_complete": False,
    "page_webassembly_enabled": False,
    "m8_complete": False,
    "m9_release_complete": False,
}
PRODUCT_MODULE_NAME = "chrome_wasm"
DEFAULT_OUT_DIR = Path("out/wasm-chrome-m6")
# Keep raw input below gzip's modulo-2^32 ISIZE boundary.
MAX_ARTIFACT_BYTES = (4 * 1024 * 1024 * 1024) - 1
SHA256_LENGTH = 64
ARTIFACT_SOURCE_PROVENANCE = "unverified"
ARTIFACT_DELIVERY = "descriptor-pinned-on-disk-read-only-snapshot"
GZIP_SCOPE = "local-mtime-zero-filename-empty-gzip-encoding-observation"
GZIP_PARAMETERS = {"compresslevel": 9, "filename": "", "mtime": 0}
LIMITATIONS = (
    "observational M9 artifact inventory only; not a performance, reliability, or release gate",
    (
        "artifact source provenance is unverified; descriptor-pinned output "
        "identities are not a clean-build attestation"
    ),
    (
        "gzip observations are local mtime-zero filename-empty encodings; they "
        "are not shipped artifacts, HTTP content encodings, or network transfer measurements"
    ),
    (
        "does not measure startup, V8, layout, raster, presentation, network, "
        "OPFS, persistent-profile behavior, memory, worker utilization, or long-run reliability"
    ),
    (
        "does not assess M7 persistent-profile completion or M8 compatibility; "
        "the M9 release gate remains false"
    ),
)

_ARTIFACT_NAMES = (f"{PRODUCT_MODULE_NAME}.js", f"{PRODUCT_MODULE_NAME}.wasm")
_BUILD_ARGS_NAME = "args.gn"
_ARTIFACT_KINDS = {
    f"{PRODUCT_MODULE_NAME}.js": "loader",
    f"{PRODUCT_MODULE_NAME}.wasm": "wasm_module",
}


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _require_positive_int(value: object, description: str) -> int:
    if type(value) is not int or value <= 0:
        raise M0Error(f"M9 artifact size inventory {description} is invalid")
    return value


def _require_exact_fields(
    value: object, expected: set[str], description: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise M0Error(f"M9 artifact size inventory {description} is invalid")
    return value


class _HashingSink:
    """A write-only sink which records a compressed stream without a file."""

    def __init__(self) -> None:
        self.byte_count = 0
        self._digest = hashlib.sha256()

    def write(self, data: bytes) -> int:
        if not isinstance(data, bytes):
            raise TypeError("gzip emitted non-bytes data")
        self.byte_count += len(data)
        self._digest.update(data)
        return len(data)

    def flush(self) -> None:
        # ``gzip.GzipFile`` does not require a flushing file object while it
        # writes, but provide the harmless file-like method for portability.
        return None

    def sha256(self) -> str:
        return self._digest.hexdigest()


class _GzipObservation:
    """Stream one fixed local gzip observation without retaining its output."""

    def __init__(self) -> None:
        self._sink = _HashingSink()
        self._stream = gzip.GzipFile(
            fileobj=self._sink,
            mode="wb",
            filename=GZIP_PARAMETERS["filename"],
            mtime=GZIP_PARAMETERS["mtime"],
            compresslevel=GZIP_PARAMETERS["compresslevel"],
        )
        self._input_bytes = 0
        self._closed = False

    def write(self, chunk: bytes) -> None:
        if self._closed:
            raise M0Error("M9 artifact size inventory gzip stream is closed")
        if not isinstance(chunk, bytes) or not chunk:
            raise M0Error("M9 artifact size inventory gzip input is invalid")
        self._input_bytes += len(chunk)
        self._stream.write(chunk)

    def finish(self) -> dict[str, object]:
        if not self._closed:
            self._stream.close()
            self._closed = True
        return {
            "bytes": self._sink.byte_count,
            "sha256": self._sink.sha256(),
            "uncompressed_bytes": self._input_bytes,
        }

    def close(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True


def _gzip_producer() -> dict[str, str]:
    runtime_version = getattr(zlib, "ZLIB_RUNTIME_VERSION", zlib.ZLIB_VERSION)
    return {
        "python_implementation": sys.implementation.name,
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "zlib_compile_version": zlib.ZLIB_VERSION,
        "zlib_runtime_version": runtime_version,
    }


def _artifact_names_for(module_name: object) -> tuple[str, str]:
    if module_name != PRODUCT_MODULE_NAME:
        raise M0Error(
            "M9 artifact size inventory only supports the fixed chrome_wasm module"
        )
    return _ARTIFACT_NAMES


def _raw_identity(capture: RegularFileHash) -> dict[str, object]:
    return {"bytes": capture.byte_count, "sha256": capture.sha256}


def collect_artifact_size_inventory(
    out_dir: Path, *, module_name: object = PRODUCT_MODULE_NAME
) -> dict[str, object]:
    """Collect one bounded, descriptor-pinned, read-only artifact observation."""

    names = _artifact_names_for(module_name)
    input_names = (_BUILD_ARGS_NAME, *names)
    encoders = {name: _GzipObservation() for name in names}

    def on_chunk(name: str, chunk: bytes) -> None:
        encoder = encoders.get(name)
        if encoder is not None:
            encoder.write(chunk)

    try:
        captures = hash_regular_files(
            Path(out_dir),
            input_names,
            maximum_bytes=MAX_ARTIFACT_BYTES,
            description="M9 Chrome Wasm artifact size inventory",
            on_chunk=on_chunk,
        )
        compressed = {name: encoders[name].finish() for name in names}
    finally:
        for encoder in encoders.values():
            encoder.close()

    artifacts: dict[str, dict[str, object]] = {}
    for name in names:
        capture = captures.get(name)
        gzip_record = compressed.get(name)
        if capture is None or gzip_record is None:
            raise M0Error("M9 artifact size inventory capture is incomplete")
        if gzip_record["uncompressed_bytes"] != capture.byte_count:
            raise M0Error("M9 artifact size inventory gzip input changed")
        artifacts[name] = {
            "gzip_observation": gzip_record,
            "kind": _ARTIFACT_KINDS[name],
            "raw": _raw_identity(capture),
        }

    raw_total_bytes = sum(
        artifact["raw"]["bytes"]  # type: ignore[index,operator]
        for artifact in artifacts.values()
    )
    gzip_total_bytes = sum(
        artifact["gzip_observation"]["bytes"]  # type: ignore[index,operator]
        for artifact in artifacts.values()
    )
    result: dict[str, object] = {
        "artifact_delivery": ARTIFACT_DELIVERY,
        "artifacts": {
            "by_name": artifacts,
            "gzip_savings_bytes": raw_total_bytes - gzip_total_bytes,
            "gzip_total_bytes": gzip_total_bytes,
            "module_name": PRODUCT_MODULE_NAME,
            "raw_total_bytes": raw_total_bytes,
        },
        "build": {
            "args_gn": _raw_identity(captures[_BUILD_ARGS_NAME]),
            "artifact_source_provenance": ARTIFACT_SOURCE_PROVENANCE,
            "input_module_name": PRODUCT_MODULE_NAME,
        },
        "case": CASE,
        "gzip_observation": {
            "content_encoding": "gzip",
            "parameters": dict(GZIP_PARAMETERS),
            "producer": _gzip_producer(),
            "scope": GZIP_SCOPE,
        },
        "gate_state": dict(EXPECTED_GATE_STATE),
        "limitations": list(LIMITATIONS),
        "m9_gate_complete": False,
        "performance_gate": False,
        "release_status": RELEASE_STATUS,
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "status": STATUS,
    }
    validate_artifact_size_inventory(result)
    return result


def _validate_artifact_record(value: object, name: str) -> tuple[int, int]:
    artifact = _require_exact_fields(
        value, {"gzip_observation", "kind", "raw"}, f"artifact {name}"
    )
    if artifact["kind"] != _ARTIFACT_KINDS[name]:
        raise M0Error("M9 artifact size inventory artifact kind is invalid")
    raw = _require_exact_fields(artifact["raw"], {"bytes", "sha256"}, "raw artifact")
    gzip_record = _require_exact_fields(
        artifact["gzip_observation"],
        {"bytes", "sha256", "uncompressed_bytes"},
        "gzip artifact",
    )
    raw_bytes = _require_positive_int(raw["bytes"], "raw artifact byte count")
    gzip_bytes = _require_positive_int(
        gzip_record["bytes"], "gzip artifact byte count"
    )
    if (
        not _is_lower_hex(raw["sha256"], SHA256_LENGTH)
        or not _is_lower_hex(gzip_record["sha256"], SHA256_LENGTH)
        or type(gzip_record["uncompressed_bytes"]) is not int
        or gzip_record["uncompressed_bytes"] != raw_bytes
    ):
        raise M0Error("M9 artifact size inventory artifact identity is invalid")
    return raw_bytes, gzip_bytes


def validate_artifact_size_inventory(result: object) -> None:
    """Reject any record that drifts from this deliberately non-release schema."""

    record = _require_exact_fields(
        result,
        {
            "artifact_delivery",
            "artifacts",
            "build",
            "case",
            "gate_state",
            "gzip_observation",
            "limitations",
            "m9_gate_complete",
            "performance_gate",
            "release_status",
            "schema_version",
            "scope",
            "status",
        },
        "result",
    )
    if (
        record["schema_version"] != SCHEMA_VERSION
        or record["case"] != CASE
        or record["scope"] != SCOPE
        or record["status"] != STATUS
        or record["release_status"] != RELEASE_STATUS
        or record["artifact_delivery"] != ARTIFACT_DELIVERY
        or record["m9_gate_complete"] is not False
        or record["performance_gate"] is not False
        or record["limitations"] != list(LIMITATIONS)
    ):
        raise M0Error("M9 artifact size inventory non-release contract is invalid")

    gate_state = _require_exact_fields(
        record["gate_state"], set(EXPECTED_GATE_STATE), "gate state"
    )
    for name, expected in EXPECTED_GATE_STATE.items():
        if gate_state[name] is not expected:
            raise M0Error("M9 artifact size inventory gate state is invalid")

    build = _require_exact_fields(
        record["build"],
        {"args_gn", "artifact_source_provenance", "input_module_name"},
        "build binding",
    )
    if (
        build["artifact_source_provenance"] != ARTIFACT_SOURCE_PROVENANCE
        or build["input_module_name"] != PRODUCT_MODULE_NAME
    ):
        raise M0Error("M9 artifact size inventory build binding is invalid")
    _require_exact_fields(build["args_gn"], {"bytes", "sha256"}, "args.gn")
    _require_positive_int(build["args_gn"]["bytes"], "args.gn byte count")
    if not _is_lower_hex(build["args_gn"]["sha256"], SHA256_LENGTH):
        raise M0Error("M9 artifact size inventory args.gn binding is invalid")

    gzip_observation = _require_exact_fields(
        record["gzip_observation"],
        {"content_encoding", "parameters", "producer", "scope"},
        "gzip observation",
    )
    if (
        gzip_observation["content_encoding"] != "gzip"
        or gzip_observation["scope"] != GZIP_SCOPE
        or gzip_observation["parameters"] != GZIP_PARAMETERS
    ):
        raise M0Error("M9 artifact size inventory gzip observation is invalid")
    producer = _require_exact_fields(
        gzip_observation["producer"],
        {
            "python_implementation",
            "python_version",
            "zlib_compile_version",
            "zlib_runtime_version",
        },
        "gzip producer",
    )
    if not all(type(value) is str and value for value in producer.values()):
        raise M0Error("M9 artifact size inventory gzip producer is invalid")

    artifacts = _require_exact_fields(
        record["artifacts"],
        {
            "by_name",
            "gzip_savings_bytes",
            "gzip_total_bytes",
            "module_name",
            "raw_total_bytes",
        },
        "artifacts",
    )
    if artifacts["module_name"] != PRODUCT_MODULE_NAME:
        raise M0Error("M9 artifact size inventory module is invalid")
    by_name = _require_exact_fields(
        artifacts["by_name"], set(_ARTIFACT_NAMES), "artifact names"
    )
    raw_total = 0
    gzip_total = 0
    for name in _ARTIFACT_NAMES:
        raw_bytes, gzip_bytes = _validate_artifact_record(by_name[name], name)
        raw_total += raw_bytes
        gzip_total += gzip_bytes
    if (
        type(artifacts["raw_total_bytes"]) is not int
        or type(artifacts["gzip_total_bytes"]) is not int
        or type(artifacts["gzip_savings_bytes"]) is not int
        or artifacts["raw_total_bytes"] != raw_total
        or artifacts["gzip_total_bytes"] != gzip_total
        or artifacts["gzip_savings_bytes"] != raw_total - gzip_total
    ):
        raise M0Error("M9 artifact size inventory totals are invalid")


def _absolute_out_dir(path: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe descriptor-pinned chrome_wasm artifact sizes without "
            "building, staging, or making a release claim."
        )
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    try:
        result = collect_artifact_size_inventory(_absolute_out_dir(args.out_dir))
        print(OBSERVED_PREFIX + _canonical_json_text(result), flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError) as exc:
        print(f"{SENTINEL}:FAIL reason={exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

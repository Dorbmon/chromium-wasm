#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Observe one bounded Canvas2D backing-store sample from a staged package.

This is deliberately a package-only public-host observation.  It serves one
verified immutable package snapshot through the normal public ``index.html``
and release host, waits for that exact outer-document epoch to report a frame,
then retains only aggregate RGB values from an 8x8 Canvas2D backing-store
sample.  It neither changes nor exports an interface from the package host.

The observation is not first visually nonempty paint, raster, compositor,
display, vsync, generic browser-readiness, compatibility, persistence, or M9
release evidence.  In particular, a black sample is valid evidence that the
bounded backing-store readback ran; it is not a failing visual assertion.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable

if __package__:
    from . import package as package_tool
    from . import run_m9_measurement_baseline as measurement_baseline
    from . import run_m9_package_browser_smoke as package_browser
    from .m0_common import M0Error, REPO_ROOT, parse_timeout
    from .m4_cdp import unused_loopback_port, wait_for_page_client
    from .m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from .m9_server_cleanup import shutdown_server_bounded
    from .run_browser_smoke import browser_command, find_browser
    from .run_m9_package_smoke import create_package_smoke_server
else:
    import package as package_tool
    import run_m9_measurement_baseline as measurement_baseline
    import run_m9_package_browser_smoke as package_browser

    from m0_common import M0Error, REPO_ROOT, parse_timeout
    from m4_cdp import unused_loopback_port, wait_for_page_client
    from m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from m9_server_cleanup import shutdown_server_bounded
    from run_browser_smoke import browser_command, find_browser
    from run_m9_package_smoke import create_package_smoke_server


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE_CANVAS_WITNESS_DOM"
RESULT_PREFIX = f"{SENTINEL}:RESULT "
PASS_MARKER = f"{SENTINEL}:PASS"
FAIL_MARKER = f"{SENTINEL}:FAIL"
SCOPE = (
    "verified-public-package-immutable-in-memory-server-snapshot-one-outer-"
    "document-canvas2d-backing-store-rgb-witness-after-report-frame-"
    "acknowledgement-only"
)
PUBLIC_MODULE_NAME = "chromium-wasm"
PACKAGE_ARTIFACT_DELIVERY = (
    "verified-package-tree-immutable-in-memory-server-snapshot"
)
WITNESS_ACKNOWLEDGEMENT = (
    "release-host-report-frame-after-synchronous-canvas2d-copy"
)
MAX_FRAME_DIMENSION = 16384
MAX_SAFE_INTEGER = (1 << 53) - 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CANVAS_PIXEL_WITNESS_GRID_COLUMNS = (
    measurement_baseline.CANVAS_PIXEL_WITNESS_GRID_COLUMNS
)
CANVAS_PIXEL_WITNESS_GRID_ROWS = (
    measurement_baseline.CANVAS_PIXEL_WITNESS_GRID_ROWS
)
CANVAS_PIXEL_WITNESS_DEFINITION = (
    measurement_baseline.CANVAS_PIXEL_WITNESS_DEFINITION
)

LIMITATIONS = (
    "does_not_retain_raw_pixels_or_screenshots",
    "does_not_claim_first_visually_nonempty_paint_raster_compositor_display_or_vsync",
    "does_not_claim_generic_browser_readiness_or_browser_ui_coverage",
    "does_not_prove_m7_persistent_profile_or_recovery",
    "does_not_prove_m8_feature_compatibility_or_page_webassembly",
    "does_not_claim_package_source_or_release_provenance",
    "does_not_complete_m9_reliability_or_release_gates",
)

_BYTE_IDENTITY_FIELDS = frozenset(("bytes", "sha256"))
_PACKAGE_ARTIFACT_FIELDS = frozenset(
    (
        "artifact_delivery",
        "artifact_source_provenance",
        "host_js",
        "index_html",
        "loader",
        "public_module_name",
        "version_json",
        "wasm",
    )
)
_RUNTIME_METADATA_FIELDS = frozenset(
    (
        "build",
        "gateState",
        "product",
        "protocol",
        "releaseStatus",
        "schemaVersion",
        "versionJsonSha256",
        "versions",
    )
)
_RUNTIME_BUILD_FIELDS = frozenset(
    (
        "artifactSourceProvenance",
        "inputModuleName",
        "resourceDelivery",
        "stagingCheckout",
    )
)
_RUNTIME_VERSION_FIELDS = frozenset(("chromium", "emscripten", "v8"))
_CANVAS_WITNESS_FIELDS = frozenset(
    (
        "acknowledgement",
        "canvas_backing_store_height",
        "canvas_backing_store_width",
        "frames_presented_at_observation",
        "witness",
    )
)
_PIXEL_WITNESS_FIELDS = frozenset(
    (
        "definition",
        "distinct_rgb_value_count",
        "non_black_rgb_sample_count",
        "sample_count",
        "sample_grid_columns",
        "sample_grid_rows",
        "visible_pixels_observed",
    )
)
_LIFECYCLE_FIELDS = frozenset(
    (
        "frames_presented_at_ready",
        "process_exit_code",
        "runtime_exit_code",
        "shutdown_disabled",
        "shutdown_requested",
    )
)
_RESULT_FIELDS = frozenset(
    (
        "canvasBackingStoreWitness",
        "limitations",
        "m9GateComplete",
        "packageArtifact",
        "packageRuntimeMetadata",
        "packageRun",
        "performanceGate",
        "releaseStatus",
        "scope",
    )
)


@dataclass(frozen=True)
class PackageCanvasWitnessSnapshot:
    """Identity and false-only metadata for an already-frozen package tree."""

    artifact_identity: dict[str, object]
    runtime_metadata: dict[str, object]


_CANVAS_PIXEL_WITNESS_EXPRESSION = f"""
(() => {{
  const canvas = document.querySelector("#browser-canvas");
  const status = document.querySelector("#chrome-status");
  if (!(canvas instanceof HTMLCanvasElement) || !(status instanceof HTMLElement)) {{
    throw new Error("package Canvas2D witness host elements are unavailable");
  }}
  let payload;
  try {{
    payload = JSON.parse(status.textContent);
  }} catch (_) {{
    throw new Error("package Canvas2D witness status is invalid");
  }}
  const framesPresented = payload && payload.framesPresented;
  if (!Number.isSafeInteger(framesPresented) || framesPresented < 1) {{
    throw new Error("package Canvas2D witness lacks a reportFrame acknowledgement");
  }}
  if (!Number.isSafeInteger(canvas.width) || !Number.isSafeInteger(canvas.height) ||
      canvas.width < 1 || canvas.width > {MAX_FRAME_DIMENSION} ||
      canvas.height < 1 || canvas.height > {MAX_FRAME_DIMENSION}) {{
    throw new Error("package Canvas2D witness canvas dimensions are invalid");
  }}
  const context = canvas.getContext("2d", {{willReadFrequently: true}});
  if (!context || typeof context.getImageData !== "function") {{
    throw new Error("package Canvas2D witness needs a readable 2D context");
  }}
  const distinctRgbValues = new Set();
  let nonblackRgbSampleCount = 0;
  for (let row = 0; row < {CANVAS_PIXEL_WITNESS_GRID_ROWS}; ++row) {{
    const y = Math.min(canvas.height - 1, Math.floor(
        (row + 0.5) * canvas.height / {CANVAS_PIXEL_WITNESS_GRID_ROWS}));
    for (let column = 0; column < {CANVAS_PIXEL_WITNESS_GRID_COLUMNS}; ++column) {{
      const x = Math.min(canvas.width - 1, Math.floor(
          (column + 0.5) * canvas.width / {CANVAS_PIXEL_WITNESS_GRID_COLUMNS}));
      const imageData = context.getImageData(x, y, 1, 1);
      if (!imageData || !(imageData.data instanceof Uint8ClampedArray) ||
          imageData.data.length !== 4) {{
        throw new Error("package Canvas2D witness returned malformed pixel data");
      }}
      const rgb = (imageData.data[0] << 16) |
          (imageData.data[1] << 8) | imageData.data[2];
      distinctRgbValues.add(rgb);
      if (rgb !== 0) {{
        nonblackRgbSampleCount += 1;
      }}
    }}
  }}
  const sampleCount = {CANVAS_PIXEL_WITNESS_GRID_COLUMNS} *
      {CANVAS_PIXEL_WITNESS_GRID_ROWS};
  return {{
    acknowledgement: {json.dumps(WITNESS_ACKNOWLEDGEMENT)},
    canvas_backing_store_height: canvas.height,
    canvas_backing_store_width: canvas.width,
    frames_presented_at_observation: framesPresented,
    witness: {{
      definition: {json.dumps(CANVAS_PIXEL_WITNESS_DEFINITION)},
      distinct_rgb_value_count: distinctRgbValues.size,
      non_black_rgb_sample_count: nonblackRgbSampleCount,
      sample_count: sampleCount,
      sample_grid_columns: {CANVAS_PIXEL_WITNESS_GRID_COLUMNS},
      sample_grid_rows: {CANVAS_PIXEL_WITNESS_GRID_ROWS},
      visible_pixels_observed: nonblackRgbSampleCount !== 0,
    }},
  }};
}})()
"""


def _exact_json_value_equal(value: object, expected: object) -> bool:
    """Compare JSON-shaped values without accepting bool/int aliases."""

    if type(value) is not type(expected):
        return False
    if type(value) is dict:
        return set(value) == set(expected) and all(
            _exact_json_value_equal(value[key], expected[key]) for key in value
        )
    if type(value) is list:
        return len(value) == len(expected) and all(
            _exact_json_value_equal(actual, wanted)
            for actual, wanted in zip(value, expected)
        )
    return value == expected


def _require_exact_fields(
    value: object, expected: frozenset[str], description: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise M0Error(f"package Canvas2D witness {description} schema is invalid")
    return value


def _require_integer(value: object, description: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > MAX_SAFE_INTEGER:
        raise M0Error(f"package Canvas2D witness {description} is invalid")
    return value


def _require_boolean(value: object, description: str) -> bool:
    if type(value) is not bool:
        raise M0Error(f"package Canvas2D witness {description} is not boolean")
    return value


def _byte_identity(contents: object, description: str) -> dict[str, object]:
    if type(contents) is not bytes or not contents:
        raise M0Error(f"package Canvas2D witness {description} bytes are invalid")
    return {
        "bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def _validate_byte_identity(value: object, description: str) -> dict[str, Any]:
    identity = _require_exact_fields(value, _BYTE_IDENTITY_FIELDS, description)
    _require_integer(identity.get("bytes"), f"{description} bytes", minimum=1)
    digest = identity.get("sha256")
    if type(digest) is not str or not SHA256_RE.fullmatch(digest):
        raise M0Error(f"package Canvas2D witness {description} SHA-256 is invalid")
    return identity


def _validate_runtime_metadata(value: object) -> dict[str, Any]:
    """Require the package's canonical false-only gate projection."""

    metadata = _require_exact_fields(value, _RUNTIME_METADATA_FIELDS, "metadata")
    if (
        metadata.get("product") != package_tool.PRODUCT_NAME
        or metadata.get("protocol") != package_tool.PACKAGE_RUNTIME_STATUS_PROTOCOL
        or metadata.get("releaseStatus") != package_tool.RELEASE_STATUS
        or metadata.get("schemaVersion") != package_tool.PACKAGE_SCHEMA_VERSION
    ):
        raise M0Error("package Canvas2D witness runtime metadata is invalid")
    version_sha256 = metadata.get("versionJsonSha256")
    if type(version_sha256) is not str or not SHA256_RE.fullmatch(version_sha256):
        raise M0Error("package Canvas2D witness VERSION.json identity is invalid")

    gate_state = metadata.get("gateState")
    if type(gate_state) is not dict or set(gate_state) != set(
        package_tool.EXPECTED_GATE_STATE
    ):
        raise M0Error("package Canvas2D witness gate state schema is invalid")
    for name, expected in package_tool.EXPECTED_GATE_STATE.items():
        if type(gate_state.get(name)) is not bool or gate_state[name] is not expected:
            raise M0Error(
                "package Canvas2D witness gate state is not the false-only contract"
            )

    build = _require_exact_fields(
        metadata.get("build"), _RUNTIME_BUILD_FIELDS, "runtime build metadata"
    )
    provenance = build.get("artifactSourceProvenance")
    if (
        type(provenance) is not str
        or provenance not in package_tool.ALLOWED_ARTIFACT_SOURCE_PROVENANCE
    ):
        raise M0Error("package Canvas2D witness artifact provenance is invalid")
    if (
        build.get("inputModuleName") != package_tool.PACKAGE_INPUT_MODULE_NAME
        or build.get("resourceDelivery") != "embedded-in-wasm-current-build"
        or type(build.get("stagingCheckout")) is not str
        or not re.fullmatch(r"[0-9a-f]{40}", build["stagingCheckout"])
    ):
        raise M0Error("package Canvas2D witness runtime build metadata is invalid")

    versions = _require_exact_fields(
        metadata.get("versions"), _RUNTIME_VERSION_FIELDS, "runtime versions"
    )
    if not all(
        type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision)
        for revision in versions.values()
    ):
        raise M0Error("package Canvas2D witness runtime versions are invalid")
    return metadata


def _artifact_contents(server: Any, name: str) -> bytes:
    try:
        contents = server.snapshot.artifacts[name]
    except (AttributeError, KeyError, TypeError) as error:
        raise M0Error(
            f"package Canvas2D witness immutable snapshot lacks {name}"
        ) from error
    if type(contents) is not bytes or not contents:
        raise M0Error(f"package Canvas2D witness snapshot {name} is invalid")
    return contents


def capture_package_canvas_witness_snapshot(
    server: Any,
) -> PackageCanvasWitnessSnapshot:
    """Bind a public-host witness to verified immutable staged package bytes."""

    try:
        artifacts = server.snapshot.artifacts
        package_tool.verify_release_snapshot(artifacts)
    except (AttributeError, TypeError, package_tool.PackageError) as error:
        raise M0Error(
            "package Canvas2D witness immutable package snapshot is invalid"
        ) from error
    metadata = _validate_runtime_metadata(
        package_browser._runtime_metadata_from_server_snapshot(server)
    )
    artifact_identity = {
        "artifact_delivery": PACKAGE_ARTIFACT_DELIVERY,
        "artifact_source_provenance": metadata["build"]["artifactSourceProvenance"],
        "host_js": _byte_identity(
            _artifact_contents(server, "chromium-wasm-host.js"), "public host"
        ),
        "index_html": _byte_identity(
            _artifact_contents(server, "index.html"), "public index"
        ),
        "loader": _byte_identity(
            _artifact_contents(server, "chromium-wasm.js"), "public loader"
        ),
        "public_module_name": PUBLIC_MODULE_NAME,
        "version_json": _byte_identity(
            _artifact_contents(server, "VERSION.json"), "VERSION.json"
        ),
        "wasm": _byte_identity(
            _artifact_contents(server, "chromium-wasm.wasm"), "public Wasm"
        ),
    }
    _validate_package_artifact_identity(
        artifact_identity, runtime_metadata=metadata, expected=artifact_identity
    )
    return PackageCanvasWitnessSnapshot(
        artifact_identity=artifact_identity,
        runtime_metadata=metadata,
    )


def _validate_package_artifact_identity(
    value: object,
    *,
    runtime_metadata: dict[str, object],
    expected: dict[str, object] | None = None,
) -> dict[str, Any]:
    artifact = _require_exact_fields(value, _PACKAGE_ARTIFACT_FIELDS, "artifact")
    if artifact.get("artifact_delivery") != PACKAGE_ARTIFACT_DELIVERY:
        raise M0Error("package Canvas2D witness artifact delivery is invalid")
    metadata = _validate_runtime_metadata(runtime_metadata)
    build = metadata["build"]
    assert isinstance(build, dict)
    if artifact.get("artifact_source_provenance") != build[
        "artifactSourceProvenance"
    ]:
        raise M0Error("package Canvas2D witness artifact provenance disagrees")
    if artifact.get("public_module_name") != PUBLIC_MODULE_NAME:
        raise M0Error("package Canvas2D witness public module name is invalid")
    identities = {
        name: _validate_byte_identity(artifact.get(name), f"artifact {name}")
        for name in ("host_js", "index_html", "loader", "version_json", "wasm")
    }
    if identities["version_json"]["sha256"] != metadata["versionJsonSha256"]:
        raise M0Error(
            "package Canvas2D witness VERSION.json identity disagrees with metadata"
        )
    if expected is not None and not _exact_json_value_equal(artifact, expected):
        raise M0Error("package Canvas2D witness artifact identity disagrees")
    return artifact


def _validate_pixel_witness(value: object) -> dict[str, Any]:
    witness = _require_exact_fields(value, _PIXEL_WITNESS_FIELDS, "pixel witness")
    if witness.get("definition") != CANVAS_PIXEL_WITNESS_DEFINITION:
        raise M0Error("package Canvas2D witness definition is invalid")
    columns = _require_integer(
        witness.get("sample_grid_columns"), "pixel witness grid columns", minimum=1
    )
    rows = _require_integer(
        witness.get("sample_grid_rows"), "pixel witness grid rows", minimum=1
    )
    if (
        columns != CANVAS_PIXEL_WITNESS_GRID_COLUMNS
        or rows != CANVAS_PIXEL_WITNESS_GRID_ROWS
    ):
        raise M0Error("package Canvas2D witness grid is invalid")
    sample_count = _require_integer(
        witness.get("sample_count"), "pixel witness sample count", minimum=1
    )
    if sample_count != columns * rows:
        raise M0Error("package Canvas2D witness sample count disagrees with grid")
    nonblack_count = _require_integer(
        witness.get("non_black_rgb_sample_count"), "pixel witness nonblack count"
    )
    distinct_count = _require_integer(
        witness.get("distinct_rgb_value_count"),
        "pixel witness distinct count",
        minimum=1,
    )
    if nonblack_count > sample_count or distinct_count > sample_count:
        raise M0Error("package Canvas2D witness RGB counts exceed its grid")
    minimum_distinct_count = 2 if 0 < nonblack_count < sample_count else 1
    maximum_distinct_count = nonblack_count + (
        1 if nonblack_count < sample_count else 0
    )
    if not minimum_distinct_count <= distinct_count <= maximum_distinct_count:
        raise M0Error("package Canvas2D witness RGB counts disagree")
    visible = _require_boolean(
        witness.get("visible_pixels_observed"), "pixel witness visible-pixels flag"
    )
    if visible != (nonblack_count != 0):
        raise M0Error("package Canvas2D witness visible-pixels flag disagrees")
    return witness


def validate_canvas_backing_store_witness(
    value: object, *, minimum_frames_presented: int
) -> dict[str, Any]:
    """Validate the aggregate public-host readback, not a visual outcome."""

    minimum_frames_presented = _require_integer(
        minimum_frames_presented, "minimum acknowledged frame count", minimum=1
    )
    observation = _require_exact_fields(
        value, _CANVAS_WITNESS_FIELDS, "backing-store observation"
    )
    if observation.get("acknowledgement") != WITNESS_ACKNOWLEDGEMENT:
        raise M0Error("package Canvas2D witness acknowledgement is invalid")
    for name in ("canvas_backing_store_width", "canvas_backing_store_height"):
        dimension = _require_integer(observation.get(name), name, minimum=1)
        if dimension > MAX_FRAME_DIMENSION:
            raise M0Error("package Canvas2D witness canvas dimension is invalid")
    observed_frames = _require_integer(
        observation.get("frames_presented_at_observation"),
        "observed frame count",
        minimum=1,
    )
    if observed_frames < minimum_frames_presented:
        raise M0Error("package Canvas2D witness predates the acknowledged frame")
    _validate_pixel_witness(observation.get("witness"))
    return observation


def capture_canvas_backing_store_witness(
    client: Any, *, minimum_frames_presented: int
) -> dict[str, Any]:
    """Ask only the live public package document for bounded RGB aggregates."""

    try:
        observed = client.evaluate(_CANVAS_PIXEL_WITNESS_EXPRESSION)
    except (AttributeError, TypeError, ValueError) as error:
        raise M0Error("package Canvas2D witness evaluation failed") from error
    return validate_canvas_backing_store_witness(
        observed, minimum_frames_presented=minimum_frames_presented
    )


def _validate_package_run(
    value: object, *, minimum_frames_presented: int
) -> dict[str, Any]:
    run = _require_exact_fields(value, _LIFECYCLE_FIELDS, "package run")
    ready_frames = _require_integer(
        run.get("frames_presented_at_ready"), "ready frame count", minimum=1
    )
    if ready_frames < minimum_frames_presented:
        raise M0Error("package Canvas2D witness run predates its first ready frame")
    if (
        type(run.get("runtime_exit_code")) is not int
        or run["runtime_exit_code"] != 0
        or type(run.get("process_exit_code")) is not int
        or run["process_exit_code"] != 0
    ):
        raise M0Error("package Canvas2D witness shutdown is not clean")
    if (
        run.get("shutdown_disabled") is not True
        or run.get("shutdown_requested") is not True
    ):
        raise M0Error("package Canvas2D witness shutdown state is invalid")
    return run


def package_canvas_witness_result(
    *,
    witness: dict[str, Any],
    package_run: dict[str, object],
    snapshot: PackageCanvasWitnessSnapshot,
) -> dict[str, object]:
    """Wrap one bounded observation in explicit pre-release package metadata."""

    result: dict[str, object] = {
        "canvasBackingStoreWitness": witness,
        "limitations": list(LIMITATIONS),
        "m9GateComplete": False,
        "packageArtifact": snapshot.artifact_identity,
        "packageRuntimeMetadata": snapshot.runtime_metadata,
        "packageRun": package_run,
        "performanceGate": False,
        "releaseStatus": package_tool.RELEASE_STATUS,
        "scope": SCOPE,
    }
    validate_package_canvas_witness_result(
        result,
        expected_snapshot=snapshot,
    )
    return result


def validate_package_canvas_witness_result(
    value: object,
    *,
    expected_snapshot: PackageCanvasWitnessSnapshot,
) -> dict[str, object]:
    """Reject results that turn a package readback into a release assertion."""

    if not isinstance(expected_snapshot, PackageCanvasWitnessSnapshot):
        raise M0Error("package Canvas2D witness expected snapshot is invalid")
    result = _require_exact_fields(value, _RESULT_FIELDS, "result")
    if result.get("scope") != SCOPE or result.get("limitations") != list(LIMITATIONS):
        raise M0Error("package Canvas2D witness result scope is invalid")
    if result.get("m9GateComplete") is not False:
        raise M0Error("package Canvas2D witness result must not complete M9")
    if result.get("performanceGate") is not False:
        raise M0Error("package Canvas2D witness result must not set a performance gate")
    if result.get("releaseStatus") != package_tool.RELEASE_STATUS:
        raise M0Error("package Canvas2D witness result release status is invalid")
    metadata = _validate_runtime_metadata(result.get("packageRuntimeMetadata"))
    if not _exact_json_value_equal(metadata, expected_snapshot.runtime_metadata):
        raise M0Error("package Canvas2D witness metadata disagrees with snapshot")
    _validate_package_artifact_identity(
        result.get("packageArtifact"),
        runtime_metadata=metadata,
        expected=expected_snapshot.artifact_identity,
    )
    package_run = _validate_package_run(
        result.get("packageRun"), minimum_frames_presented=1
    )
    witness = validate_canvas_backing_store_witness(
        result.get("canvasBackingStoreWitness"),
        minimum_frames_presented=package_run["frames_presented_at_ready"],
    )
    if witness["frames_presented_at_observation"] < package_run[
        "frames_presented_at_ready"
    ]:
        raise M0Error("package Canvas2D witness predates the ready package frame")
    return result


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    try:
        action()
    except BaseException as error:
        if cleanup_error is None:
            return error
    return cleanup_error


def _join_package_canvas_witness_server(thread: threading.Thread) -> None:
    thread.join(timeout=5)
    if thread.is_alive():
        raise M0Error("package Canvas2D witness server did not stop")


def run_package_canvas_witness_smoke(
    *,
    dist_dir: Path,
    browser_argument: Path | None,
    no_sandbox: bool,
    timeout: float,
) -> dict[str, object]:
    """Run one public package lifetime and capture its bounded pixel witness."""

    server: Any = None
    server_thread: threading.Thread | None = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    stderr_reader: BrowserStderrReader | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    client: Any = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    primary_error: BaseException | None = None
    try:
        browser_path, _browser_version = find_browser(browser_argument)
        server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
        snapshot = capture_package_canvas_witness_snapshot(server)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-package-canvas-witness-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        host, port = server.server_address[:2]
        package_url = f"http://{host}:{port}/"
        epoch = secrets.token_urlsafe(18)
        package_url = package_browser._make_epoch_url(package_url, epoch)
        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m9-package-canvas-witness-"
        )
        debug_port = unused_loopback_port()
        command = browser_command(
            browser_path, profile.name, package_url, no_sandbox=no_sandbox
        )
        command[1:1] = [
            "--enable-logging=stderr",
            "--remote-allow-origins=http://localhost",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
        ]
        browser = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        stderr_reader = BrowserStderrReader(
            browser.stderr,
            browser_stderr,
            name="chromium-wasm-m9-package-canvas-witness-browser-stderr",
            thread_factory=threading.Thread,
        )
        stderr_reader.start()
        deadline = time.monotonic() + timeout
        client = wait_for_page_client(debug_port, package_url, deadline)
        ready, time_origin = package_browser._wait_for_ready_package_document(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_url=package_url,
            expected_epoch=epoch,
            expected_package_metadata=snapshot.runtime_metadata,
            prior_time_origin=None,
            description="waiting for the public package frame acknowledgement",
        )
        ready_frames = _require_integer(
            ready.get("framesPresented"), "ready frame count", minimum=1
        )
        witness = capture_canvas_backing_store_witness(
            client, minimum_frames_presented=ready_frames
        )

        # Rebind the witness to the same immutable metadata and exact outer
        # document epoch before requesting shutdown.  This does not inspect or
        # require firstVisuallyNonEmptyPaint.
        post_witness_status = package_browser._status(client)
        package_browser._validate_fatal_health(post_witness_status)
        package_browser._require_ready_package_document(
            post_witness_status,
            expected_url=package_url,
            expected_epoch=epoch,
            expected_package_metadata=snapshot.runtime_metadata,
            prior_time_origin=None,
        )
        post_witness_frames = _require_integer(
            post_witness_status.get("framesPresented"),
            "post-witness frame count",
            minimum=ready_frames,
        )
        if post_witness_frames < witness["frames_presented_at_observation"]:
            raise M0Error(
                "package Canvas2D witness is newer than its post-witness status"
            )
        shutdown = package_browser._request_clean_shutdown(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_url=package_url,
            expected_epoch=epoch,
            expected_package_metadata=snapshot.runtime_metadata,
            expected_time_origin=time_origin,
            description="waiting for clean package-host shutdown after witness",
        )
        result = package_canvas_witness_result(
            witness=witness,
            package_run={
                "frames_presented_at_ready": ready_frames,
                "process_exit_code": shutdown.get("processExitCode"),
                "runtime_exit_code": shutdown.get("runtimeExitCode"),
                "shutdown_disabled": shutdown.get("shutdownDisabled"),
                "shutdown_requested": shutdown.get("shutdownRequested"),
            },
            snapshot=snapshot,
        )
        return result
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_error: BaseException | None = None
        if client is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, client.close)
        if browser is not None and stderr_reader is not None and stderr_reader.started:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: stop_browser_group(browser, stderr_reader)
            )
        elif browser is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: abort_browser_group(browser, stderr_reader)
            )
        if server is not None:
            if server_thread_started:
                cleanup_error = _run_cleanup_action(
                    cleanup_error,
                    lambda: shutdown_server_bounded(
                        server,
                        timeout=5,
                        description="M9 package Canvas2D witness server",
                    ),
                )
            cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
        if server_thread_started and server_thread is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: _join_package_canvas_witness_server(server_thread),
            )
        if server is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: server.join_request_handlers(
                    timeout=5, description="M9 package Canvas2D witness server"
                ),
            )
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe a bounded Canvas2D backing-store witness from a verified "
            "pre-release Chromium Wasm package."
        )
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 10.0:
        parser.error("--timeout must allow package startup, witness, and shutdown")
    try:
        result = run_package_canvas_witness_smoke(
            dist_dir=args.dist_dir,
            browser_argument=args.browser,
            no_sandbox=args.no_sandbox,
            timeout=args.timeout,
        )
        print(
            RESULT_PREFIX
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(PASS_MARKER, flush=True)
        return 0
    except (M0Error, OSError, TypeError, ValueError) as error:
        print(f"{FAIL_MARKER} reason={error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

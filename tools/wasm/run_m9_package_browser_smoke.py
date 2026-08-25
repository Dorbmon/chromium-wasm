#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Boot a staged pre-release package in a real browser.

The package intentionally contains ``chromium-wasm.js`` rather than the input
target's ``chrome_wasm.js`` name. This smoke serves *only* the staged names;
therefore a successful frame proves the release host's Blob-backed Emscripten
pthread loader route and renamed Wasm locateFile mapping.  Its optional second
epoch first performs an orderly host shutdown, then navigates the *outer*
document and requires a fresh packaged loader lifetime in the same host
browser. An optional credential-free WSS endpoint is installed through CDP
before each package document begins; it proves only release-host configuration
handoff, not a live carrier or Chromium network request. It is not an M6 UI,
M7 persistence, M8 compatibility, or M9 release acceptance test.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if __package__:
    from . import package as package_tool
    from .m0_common import M0Error, REPO_ROOT, parse_timeout
    from .m4_cdp import unused_loopback_port, wait_for_page_client
    from .run_browser_smoke import (
        browser_command,
        find_browser,
    )
    from .m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from .m9_server_cleanup import shutdown_server_bounded
    from .run_m9_package_smoke import (
        EPOCH_QUERY_KEY,
        EPOCH_ROUTE_PREFIX,
        create_package_smoke_server,
    )
else:
    import package as package_tool

    from m0_common import M0Error, REPO_ROOT, parse_timeout
    from m4_cdp import unused_loopback_port, wait_for_page_client
    from run_browser_smoke import (
        browser_command,
        find_browser,
    )
    from m9_browser_cleanup import (
        BrowserStderrReader,
        abort_browser_group,
        stop_browser_group,
    )
    from m9_server_cleanup import shutdown_server_bounded
    from run_m9_package_smoke import (
        EPOCH_QUERY_KEY,
        EPOCH_ROUTE_PREFIX,
        create_package_smoke_server,
    )


SENTINEL = "CHROMIUM_WASM_M9_PACKAGE"
SCOPE = "real-browser-package-loader-pthread-bootstrap-and-host-shutdown-only"
OUTER_DOCUMENT_RESTART_SCOPE = (
    "real-browser-package-two-outer-document-epochs-loader-pthread-bootstrap-"
    "and-host-shutdown-only"
)
OUTER_DOCUMENT_RELOAD_STRESS_EPOCH_COUNT = 3
OUTER_DOCUMENT_RELOAD_STRESS_RESTART_COUNT = (
    OUTER_DOCUMENT_RELOAD_STRESS_EPOCH_COUNT - 1
)
# This deliberately observes only a short fixed host-side interval after an
# acknowledged native/runtime exit. It catches a late canvas presentation
# callback before the next outer-document navigation without claiming that all
# native, worker, or JavaScript resources have been reclaimed.
POST_EXIT_FRAME_QUIESCENCE_SECONDS = 0.1
# This is deliberately a fixed, small reliability probe rather than an
# unbounded command-line stress loop.  The M9 runner below accepts at most the
# two restarts needed by the separate three-epoch package-reload observation.
MAX_OUTER_DOCUMENT_RESTARTS = OUTER_DOCUMENT_RELOAD_STRESS_RESTART_COUNT
OUTER_DOCUMENT_RELOAD_STRESS_SCOPE = (
    "real-browser-package-three-outer-document-epochs-loader-pthread-bootstrap-"
    "runtime-core-resource-timing-and-local-server-receipt-and-host-shutdown-only"
)
OUTER_DOCUMENT_RELOAD_STRESS_LIMITATIONS = (
    "fixed-three-epoch-outer-document-reload-observation-only",
    "fixed-100ms-post-exit-host-frame-quiescence-only",
    "local-server-receipt-uses-only-an-immutable-same-origin-test-route-with-"
    "cache-control-no-store",
    "does_not_measure_resource-transfer-bytes-general-http-caching-or-external-delivery",
    "does_not_establish_long_run_reliability_or_resource_leak_freedom",
    "does_not_measure_memory_worker_exhaustion_or_out_of_memory_behavior",
    "does_not_measure_live_transport_or_resource_teardown",
    "does_not_establish_m7_persistence_m8_compatibility_or_m9_release_completion",
)
RELEASE_STATUS = package_tool.RELEASE_STATUS
MAX_SAFE_INTEGER = (1 << 53) - 1
PACKAGE_OBSERVATION_SCHEMA_VERSION = 1
PACKAGE_OBSERVATION_SCOPE = (
    "one-fresh-profile-real-browser-launch-to-first-package-readiness-"
    "runner-monotonic-observation"
)
PACKAGE_OBSERVATION_ARTIFACT_DELIVERY = (
    "verified-immutable-in-memory-package-server-snapshot-raw-artifact-bytes"
)
PACKAGE_OBSERVATION_COMPRESSION = "not-measured"
PACKAGE_OBSERVATION_LIMITS = (
    "one fresh browser launch and one runner-ready observation only; not a "
    "cross-run benchmark or performance gate",
    "elapsed time begins immediately before the host browser process launch "
    "and ends when the runner observes the first ready package document; it "
    "includes browser launch, profile setup, DevTools attachment, server "
    "scheduling, and runner polling",
    "raw artifact bytes identify the immutable package snapshot only; they do "
    "not measure HTTP compression, transfer bytes, network latency, caching, "
    "or external release-server delivery",
    "runtime artifact verification and raw artifact bytes do not measure "
    "physical copies, JavaScript heap, Wasm linear memory, committed or "
    "resident memory, allocation behavior, or leaks",
    "this observation does not establish M7 persistence, M8 compatibility, "
    "or M9 release completion",
)
MAX_RELEASE_WISP_ENDPOINT_CHARACTERS = 2048
RELEASE_WISP_CONFIGURATION_GLOBAL = "__chromiumWasmReleaseWispV1"
RELEASE_WISP_CONFIGURATION_VERSION = 1
WISP_BOOTSTRAP_URL = "about:blank"
RUNTIME_CORE_RESOURCE_RECEIPT = (
    ("chromium-wasm-host.js", "script"),
    ("chromium-wasm-pointer-input.js", "script"),
    ("chromium-wasm-clipboard-input.js", "script"),
    ("chromium-wasm-file-picker.js", "script"),
    ("chromium-wasm-storage-estimate.js", "script"),
    ("chromium-wasm-text-input.js", "script"),
    ("chromium-wasm-release-wisp-config.js", "script"),
    ("VERSION.json", "fetch"),
    ("chromium-wasm.js", "fetch"),
    ("chromium-wasm.wasm", "fetch"),
)
_RUNTIME_CORE_RESOURCE_RECEIPT_FIELDS = frozenset(("initiator_type", "path"))
_RUNTIME_CORE_SERVER_RECEIPT_FIELDS = frozenset(("path", "successful_get_count"))

_STATUS_EXPRESSION = r"""
(() => {
  const navigation = performance.getEntriesByType("navigation")[0];
  const documentIdentity = {
    href: location.href,
    navigation: navigation && typeof navigation === "object" ? {
      name: navigation.name,
      startTime: navigation.startTime,
      type: navigation.type,
    } : null,
    timeOrigin: performance.timeOrigin,
  };
  const root = document.querySelector("#chrome-root");
  const status = document.querySelector("#chrome-status");
  const shutdown = document.querySelector("#shutdown");
  const versions = document.querySelector("#versions");
  if (!(root instanceof HTMLElement) || !(status instanceof HTMLElement) ||
      !(shutdown instanceof HTMLButtonElement) ||
      !(versions instanceof HTMLElement)) {
    // CDP can list a target while its initial document is still being
    // replaced by the staged package index. Treat that transient state as
    // pending rather than attaching a false permanent page failure to the
    // correct URL before its DOM is installed.
    return {
      documentIdentity,
      documentReadyState: document.readyState,
      pending: true,
      statusText: "package host elements are not installed yet",
    };
  }
  let payload = null;
  try {
    payload = JSON.parse(status.textContent);
  } catch (_) {
    return {
      crossOriginIsolated: globalThis.crossOriginIsolated === true,
      documentIdentity,
      pageState: root.dataset.state,
      pending: true,
      statusText: status.textContent.slice(0, 256),
    };
  }
  return {
    crossOriginIsolated: globalThis.crossOriginIsolated === true,
    documentIdentity,
    fatalCount: payload.fatalCount,
    framesPresented: payload.framesPresented,
    pageState: root.dataset.state,
    packageMetadata: payload.packageMetadata,
    readiness: payload.readiness,
    records: payload.records,
    releaseStatus: payload.releaseStatus,
    runtimeInitialized: payload.runtimeInitialized,
    runtimeArtifactsVerified: payload.runtimeArtifactsVerified,
    runtimeExitCode: payload.runtimeExitCode,
    processExitCode: payload.processExitCode,
    shutdownDisabled: shutdown.disabled,
    shutdownRequested: payload.shutdownRequested,
    wispConfigured: payload.wispConfigured,
    displayedVersions: versions.textContent,
  };
})()
"""


def _runtime_metadata_from_server_snapshot(server: Any) -> dict[str, object]:
    try:
        artifacts = server.snapshot.artifacts
        version_bytes = artifacts["VERSION.json"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise M0Error("package server is missing its immutable VERSION.json") from exc
    try:
        package_tool.verify_release_snapshot(artifacts)
        return package_tool.package_runtime_status_metadata(version_bytes)
    except package_tool.PackageError as exc:
        raise M0Error(f"package server snapshot metadata is invalid: {exc}") from exc


def _package_observation_artifact_bytes(server: Any) -> dict[str, int]:
    """Return raw byte counts from the already-verified server snapshot.

    This deliberately does not re-hash the large Wasm module after server
    creation. ``create_package_smoke_server`` has already captured and
    verified these immutable bytes before exposing the snapshot to this
    runner. The counts describe raw snapshot bytes, not compression, transfer,
    cache, allocation, or resident-memory measurements.
    """

    try:
        artifacts = server.snapshot.artifacts
        verification = server.snapshot.verification
        artifact_count = verification["artifact_count"]
        release_status = verification["release_status"]
        loader = artifacts["chromium-wasm.js"]
        wasm = artifacts["chromium-wasm.wasm"]
        values = artifacts.values()
    except (AttributeError, KeyError, TypeError) as exc:
        raise M0Error("package observation server snapshot is invalid") from exc
    if (
        type(artifact_count) is not int
        or artifact_count <= 0
        # VERSION.json describes the other package files; it cannot include
        # its own final hash/size record without a circular identity.
        or artifact_count != len(artifacts) - 1
        or release_status != RELEASE_STATUS
        or type(loader) is not bytes
        or not loader
        or type(wasm) is not bytes
        or not wasm
    ):
        raise M0Error("package observation server snapshot is invalid")
    total_bytes = 0
    for contents in values:
        if type(contents) is not bytes or not contents:
            raise M0Error("package observation server snapshot is invalid")
        total_bytes += len(contents)
    if total_bytes <= 0:
        raise M0Error("package observation raw artifact size is invalid")
    return {
        "loader_raw_bytes": len(loader),
        "package_raw_bytes": total_bytes,
        "snapshot_artifact_count": len(artifacts),
        "wasm_raw_bytes": len(wasm),
        "versioned_artifact_count": artifact_count,
    }


def _package_startup_observation(
    *, server: Any, ready: dict[str, Any], launch_started_at: object
) -> dict[str, object]:
    """Build one bounded, explicitly non-gating package startup observation."""

    if ready.get("runtimeArtifactsVerified") is not True:
        raise M0Error("package observation requires verified runtime artifacts")
    if (
        isinstance(launch_started_at, bool)
        or not isinstance(launch_started_at, (int, float))
        or not math.isfinite(float(launch_started_at))
        or float(launch_started_at) < 0
    ):
        raise M0Error("package observation launch timestamp is invalid")
    launch_started = float(launch_started_at)
    ready_observed_at = time.monotonic()
    if not math.isfinite(ready_observed_at) or ready_observed_at < launch_started:
        raise M0Error("package observation ready timestamp is invalid")
    elapsed_ms = round((ready_observed_at - launch_started) * 1000, 3)
    if not math.isfinite(elapsed_ms) or elapsed_ms < 0:
        raise M0Error("package observation startup duration is invalid")
    return {
        "artifact_bytes": _package_observation_artifact_bytes(server),
        "artifact_delivery": PACKAGE_OBSERVATION_ARTIFACT_DELIVERY,
        "browser_launch_to_ready_observed_ms": elapsed_ms,
        "compression": PACKAGE_OBSERVATION_COMPRESSION,
        "m9_gate_complete": False,
        "measurement_limits": list(PACKAGE_OBSERVATION_LIMITS),
        "performance_gate": False,
        "release_status": RELEASE_STATUS,
        "runtime_artifacts_verified": True,
        "schema_version": PACKAGE_OBSERVATION_SCHEMA_VERSION,
        "scope": PACKAGE_OBSERVATION_SCOPE,
    }


def _exact_json_value_equal(actual: object, expected: object) -> bool:
    """Compare JSON-shaped values without Python bool/int coercion."""

    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        if set(actual) != set(expected):
            return False
        return all(
            _exact_json_value_equal(actual[key], expected[key])
            for key in actual
        )
    if type(actual) is list:
        return len(actual) == len(expected) and all(
            _exact_json_value_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def _require_runtime_metadata(
    value: object, expected: dict[str, object]
) -> None:
    """Require the ready host's bounded metadata to equal the server snapshot."""
    if not _exact_json_value_equal(value, expected):
        raise M0Error(
            "package host runtime metadata does not match immutable "
            "VERSION.json snapshot"
        )


def _status(client: Any) -> dict[str, Any]:
    value = client.evaluate(_STATUS_EXPRESSION)
    if not isinstance(value, dict):
        raise M0Error("package host status is not an object")
    return value


def _runtime_core_resource_receipt_expression(expected_url: str) -> str:
    """Build a read-only current-document Resource Timing receipt query."""

    try:
        parsed = urlsplit(expected_url)
    except (TypeError, ValueError) as exc:
        raise M0Error("package runtime resource receipt URL is invalid") from exc
    if (
        not isinstance(expected_url, str)
        or parsed.scheme != "http"
        or not parsed.netloc
        or parsed.fragment
    ):
        raise M0Error("package runtime resource receipt URL is invalid")
    expected_resources = [
        {"initiatorType": initiator_type, "path": path}
        for path, initiator_type in RUNTIME_CORE_RESOURCE_RECEIPT
    ]
    return f"""
(() => {{
  const expectedDocumentUrl = {json.dumps(expected_url)};
  const expectedResources = {json.dumps(expected_resources, separators=(",", ":"))};
  if (location.href !== expectedDocumentUrl) {{
    return null;
  }}
  const documentUrl = new URL(expectedDocumentUrl);
  const expectedByUrl = new Map();
  for (const expected of expectedResources) {{
    if (!expected || typeof expected.path !== "string" ||
        typeof expected.initiatorType !== "string") {{
      return null;
    }}
    const resourceUrl = new URL(`./${{expected.path}}`, documentUrl);
    if (resourceUrl.origin !== documentUrl.origin || resourceUrl.search !== "" ||
        resourceUrl.hash !== "" || expectedByUrl.has(resourceUrl.href)) {{
      return null;
    }}
    expectedByUrl.set(resourceUrl.href, expected);
  }}
  const observed = new Map();
  const entries = performance.getEntriesByType("resource");
  if (!Array.isArray(entries)) {{
    return null;
  }}
  for (const entry of entries) {{
    if (!entry || typeof entry.name !== "string" ||
        typeof entry.initiatorType !== "string") {{
      continue;
    }}
    const expected = expectedByUrl.get(entry.name);
    if (expected && entry.initiatorType === expected.initiatorType) {{
      observed.set(expected.path, {{
        initiator_type: expected.initiatorType,
        path: expected.path,
      }});
    }}
  }}
  return expectedResources.filter((expected) => observed.has(expected.path)).map(
      (expected) => observed.get(expected.path));
}})()
"""


def validate_runtime_core_resource_receipt(value: object) -> list[dict[str, str]]:
    """Require the exact, bounded package runtime-resource receipt."""

    expected = [
        {"initiator_type": initiator_type, "path": path}
        for path, initiator_type in RUNTIME_CORE_RESOURCE_RECEIPT
    ]
    if type(value) is not list or len(value) != len(expected):
        raise M0Error("package runtime resource receipt is incomplete")
    normalized: list[dict[str, str]] = []
    for index, (observed, expected_entry) in enumerate(zip(value, expected), start=1):
        if (
            type(observed) is not dict
            or set(observed) != _RUNTIME_CORE_RESOURCE_RECEIPT_FIELDS
        ):
            raise M0Error(f"package runtime resource receipt {index} is malformed")
        path = observed.get("path")
        initiator_type = observed.get("initiator_type")
        if type(path) is not str or type(initiator_type) is not str:
            raise M0Error(f"package runtime resource receipt {index} is malformed")
        if path != expected_entry["path"]:
            raise M0Error(f"package runtime resource receipt {index} path is invalid")
        if initiator_type != expected_entry["initiator_type"]:
            raise M0Error(
                f"package runtime resource receipt {index} initiator is invalid"
            )
        normalized.append({"initiator_type": initiator_type, "path": path})
    return normalized


def _capture_runtime_core_resource_receipt(
    client: Any, *, expected_url: str
) -> list[dict[str, str]]:
    """Capture only current-document core package resource names and roles."""

    value = client.evaluate(_runtime_core_resource_receipt_expression(expected_url))
    return validate_runtime_core_resource_receipt(value)


def validate_runtime_core_server_receipt(
    value: object,
) -> list[dict[str, object]]:
    """Require one successful local-server GET for every core package resource.

    The fixed three-epoch stress uses an opaque same-origin path component for
    each outer document.  This receipt is deliberately narrower than general
    HTTP-cache or external-delivery evidence: it proves only what the local
    immutable-snapshot server received for that one path namespace.
    """

    expected_paths = [path for path, _initiator in RUNTIME_CORE_RESOURCE_RECEIPT]
    if type(value) is not list or len(value) != len(expected_paths):
        raise M0Error("package runtime server receipt is incomplete")
    normalized: list[dict[str, object]] = []
    for index, (observed, expected_path) in enumerate(
        zip(value, expected_paths), start=1
    ):
        if (
            type(observed) is not dict
            or set(observed) != _RUNTIME_CORE_SERVER_RECEIPT_FIELDS
        ):
            raise M0Error(f"package runtime server receipt {index} is malformed")
        path = observed.get("path")
        successful_get_count = observed.get("successful_get_count")
        if type(path) is not str or path != expected_path:
            raise M0Error(f"package runtime server receipt {index} path is invalid")
        if type(successful_get_count) is not int or successful_get_count != 1:
            raise M0Error(
                f"package runtime server receipt {index} successful GET count is invalid"
            )
        normalized.append(
            {"path": path, "successful_get_count": successful_get_count}
        )
    return normalized


def _capture_runtime_core_server_receipt(
    server: Any, *, epoch: str
) -> list[dict[str, object]]:
    """Project one server-side epoch log into a bounded package receipt."""

    if not isinstance(epoch, str) or not epoch:
        raise M0Error("package runtime server receipt epoch is invalid")
    try:
        counts = server.epoch_successful_get_counts(epoch)
    except (AttributeError, TypeError) as exc:
        raise M0Error("package server does not expose an epoch GET receipt") from exc
    if type(counts) is not dict:
        raise M0Error("package server epoch GET receipt is invalid")
    document_get_count = counts.get("/")
    if type(document_get_count) is not int or document_get_count != 1:
        raise M0Error("package epoch document GET receipt is invalid")
    receipt = [
        {
            "path": path,
            "successful_get_count": counts.get(f"/{path}"),
        }
        for path, _initiator in RUNTIME_CORE_RESOURCE_RECEIPT
    ]
    return validate_runtime_core_server_receipt(receipt)


def _normalize_release_wisp_endpoint(value: object) -> str:
    """Accept only the public WSS carrier shape used by the release host.

    The generated host is still the authoritative validator and normalizer.
    This runner repeats the security boundary only to avoid putting a malformed
    or credential-bearing command-line value into a DevTools init script. Its
    failure strings intentionally never include the supplied endpoint.
    """

    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_RELEASE_WISP_ENDPOINT_CHARACTERS
        or value != value.strip()
    ):
        raise M0Error("release WISP endpoint is invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
        # Accessing .port forces urllib to reject an invalid port rather than
        # allowing a differently parsed carrier through this preflight.
        _ = parsed.port
    except ValueError as exc:
        raise M0Error("release WISP endpoint is invalid") from exc
    if (
        parsed.scheme != "wss"
        or not parsed.netloc
        or not hostname
        or username is not None
        or password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/")
    ):
        raise M0Error("release WISP endpoint violates the transport policy")
    return value


def _release_wisp_init_script(endpoint: str) -> str:
    """Produce an idempotent, pre-document CDP configuration script.

    The endpoint literal is necessarily present in DevTools' in-memory source,
    but this helper and all callers keep it out of logs, errors, and the
    runner's structured result.  Re-registering an identical source before a
    later outer-document navigation is safe: each new realm receives the same
    immutable own data property once or validates the property installed by a
    prior registration.
    """

    normalized_endpoint = _normalize_release_wisp_endpoint(endpoint)
    configuration_json = json.dumps(
        {
            "endpoint": normalized_endpoint,
            "version": RELEASE_WISP_CONFIGURATION_VERSION,
        },
        separators=(",", ":"),
    )
    global_json = json.dumps(RELEASE_WISP_CONFIGURATION_GLOBAL)
    return (
        "(() => {\n"
        f"  const configuration = Object.freeze({configuration_json});\n"
        f"  const descriptor = Object.getOwnPropertyDescriptor(globalThis, {global_json});\n"
        "  if (descriptor === undefined) {\n"
        f"    Object.defineProperty(globalThis, {global_json}, {{\n"
        "      configurable: false,\n"
        "      enumerable: false,\n"
        "      value: configuration,\n"
        "      writable: false,\n"
        "    });\n"
        "    return;\n"
        "  }\n"
        "  if (!Object.hasOwn(descriptor, \"value\") || descriptor.configurable ||\n"
        "      descriptor.enumerable || descriptor.writable || !descriptor.value ||\n"
        "      descriptor.value.version !== configuration.version ||\n"
        "      descriptor.value.endpoint !== configuration.endpoint) {\n"
        "    throw new Error(\"release WISP configuration collision\");\n"
        "  }\n"
        "})();"
    )


def _install_release_wisp_configuration(client: Any, endpoint: str) -> None:
    """Install configuration before the next document starts, or fail closed."""

    source = _release_wisp_init_script(endpoint)
    try:
        # Chrome does not activate Page.addScriptToEvaluateOnNewDocument for a
        # raw remote-debugging connection until the Page domain is enabled.
        # Do this before the package navigation, not after a host document has
        # started executing.
        client.call("Page.enable")
        response = client.call(
            "Page.addScriptToEvaluateOnNewDocument", {"source": source}
        )
    except Exception as exc:
        raise M0Error("DevTools could not install release WISP configuration") from exc
    identifier = response.get("identifier") if isinstance(response, dict) else None
    if not isinstance(identifier, str) or not identifier:
        raise M0Error("DevTools did not acknowledge release WISP configuration")


def _navigate_to_package_document(client: Any, package_url: str) -> None:
    """Start exactly one package document after any required init script."""

    try:
        response = client.call("Page.navigate", {"url": package_url})
    except Exception as exc:
        raise M0Error("DevTools could not navigate to the package document") from exc
    frame_id = response.get("frameId") if isinstance(response, dict) else None
    if not isinstance(frame_id, str) or not frame_id:
        raise M0Error("DevTools did not acknowledge package document navigation")


def _require_release_wisp_configuration(
    status: dict[str, Any], expected: bool
) -> None:
    """Bind host status to the redacted pre-navigation configuration state."""
    observed = status.get("wispConfigured")
    if observed is not expected:
        observed_state = (
            "enabled" if observed is True else "disabled" if observed is False else "missing"
        )
        expected_state = "enabled" if expected else "disabled"
        raise M0Error(
            "package host WISP configuration state is invalid "
            f"(expected {expected_state}, observed {observed_state})"
        )


def _make_epoch_url(url: str, epoch: str) -> str:
    """Add one exact, single-use document epoch to a package URL."""

    if not isinstance(epoch, str) or not epoch:
        raise M0Error("package document epoch is invalid")
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.netloc or parsed.fragment:
        raise M0Error("package document URL is invalid")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == EPOCH_QUERY_KEY for key, _value in pairs):
        raise M0Error("package document URL already contains an epoch")
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            urlencode([*pairs, (EPOCH_QUERY_KEY, epoch)]),
            "",
        )
    )


def _register_epoch_document_url(server: Any, package_url: str, epoch: str) -> str:
    """Bind one stress-only document URL to the server's opaque epoch route."""

    if not isinstance(package_url, str) or not isinstance(epoch, str) or not epoch:
        raise M0Error("package epoch document URL is invalid")
    try:
        route_path = server.register_epoch_route(epoch)
    except (AttributeError, TypeError) as exc:
        raise M0Error("package server does not expose an epoch route") from exc
    expected_route_path = f"{EPOCH_ROUTE_PREFIX}{epoch}/"
    if route_path != expected_route_path:
        raise M0Error("package server epoch route is invalid")
    try:
        parsed = urlsplit(package_url)
    except (TypeError, ValueError) as exc:
        raise M0Error("package epoch document URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise M0Error("package epoch document URL is invalid")
    return _make_epoch_url(
        urlunsplit((parsed.scheme, parsed.netloc, route_path, "", "")), epoch
    )


def _require_document_identity(
    status: dict[str, Any],
    *,
    expected_url: str,
    expected_epoch: str,
    prior_time_origin: float | None = None,
) -> float:
    """Bind a ready package host to one exact outer-document lifetime.

    A Page target URL alone can describe a navigation in progress or an old
    attached document.  Require the exact epoch-bearing URL from both the
    document and Navigation Timing, then retain its independent time origin.
    The caller compares the origin across outer-document lifetimes.
    """

    identity = status.get("documentIdentity")
    if not isinstance(identity, dict):
        raise M0Error("package host document identity is missing")
    observed_url = identity.get("href")
    if not isinstance(observed_url, str) or observed_url != expected_url:
        raise M0Error("package host document URL does not match its epoch")
    parsed = urlsplit(observed_url)
    epoch_values = [
        value
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key == EPOCH_QUERY_KEY
    ]
    if epoch_values != [expected_epoch]:
        raise M0Error("package host document epoch is invalid")

    navigation = identity.get("navigation")
    if not isinstance(navigation, dict):
        raise M0Error("package host navigation timing identity is missing")
    if navigation.get("name") != expected_url or navigation.get("type") != "navigate":
        raise M0Error("package host navigation timing URL does not match its epoch")
    start_time = navigation.get("startTime")
    if isinstance(start_time, bool) or not isinstance(start_time, (int, float)):
        raise M0Error("package host navigation timing start is invalid")
    if not math.isfinite(float(start_time)) or float(start_time) < 0:
        raise M0Error("package host navigation timing start is invalid")

    time_origin = identity.get("timeOrigin")
    if isinstance(time_origin, bool) or not isinstance(time_origin, (int, float)):
        raise M0Error("package host document time origin is invalid")
    result = float(time_origin)
    if not math.isfinite(result) or result <= 0:
        raise M0Error("package host document time origin is invalid")
    if prior_time_origin is not None and result == prior_time_origin:
        raise M0Error("package host outer-document time origin did not change")
    return result


def _require_ready_package_document(
    status: dict[str, Any],
    *,
    expected_url: str,
    expected_epoch: str,
    expected_package_metadata: dict[str, object],
    prior_time_origin: float | None = None,
) -> float:
    """Bind one ready document to both its URL epoch and served metadata."""

    _require_runtime_metadata(status.get("packageMetadata"), expected_package_metadata)
    return _require_document_identity(
        status,
        expected_url=expected_url,
        expected_epoch=expected_epoch,
        prior_time_origin=prior_time_origin,
    )


def _require_terminal_package_document(
    status: dict[str, Any],
    *,
    expected_url: str,
    expected_epoch: str,
    expected_package_metadata: dict[str, object],
    expected_time_origin: float,
) -> None:
    """Bind terminal exit evidence to the exact ready package document."""

    if (
        isinstance(expected_time_origin, bool)
        or not isinstance(expected_time_origin, (int, float))
        or not math.isfinite(float(expected_time_origin))
        or float(expected_time_origin) <= 0
    ):
        raise M0Error("expected package ready document time origin is invalid")
    _require_runtime_metadata(status.get("packageMetadata"), expected_package_metadata)
    observed_time_origin = _require_document_identity(
        status,
        expected_url=expected_url,
        expected_epoch=expected_epoch,
    )
    if observed_time_origin != float(expected_time_origin):
        raise M0Error(
            "package host shutdown document time origin does not match ready document"
        )


def _is_clean_shutdown(status: dict[str, Any]) -> bool:
    runtime_exit_code = status.get("runtimeExitCode")
    process_exit_code = status.get("processExitCode")
    return (
        _has_zero_fatal_count(status)
        and status.get("shutdownRequested") is True
        and status.get("shutdownDisabled") is True
        and type(runtime_exit_code) is int
        and runtime_exit_code == 0
        and type(process_exit_code) is int
        and process_exit_code == 0
        and runtime_exit_code == process_exit_code
    )


def _require_clean_shutdown(status: dict[str, Any], description: str) -> None:
    if not _is_clean_shutdown(status):
        raise M0Error(
            f"{description} did not complete with zero fatal count and matching "
            "runtime and native process exit codes 0"
        )


def _require_post_exit_frame_quiescence_sample(
    status: dict[str, Any], expected_frame_count: int
) -> None:
    """Require that one cleanly exited host presents no later canvas frame."""

    if type(expected_frame_count) is not int or expected_frame_count < 1:
        raise M0Error("expected post-exit package frame count is invalid")
    _require_clean_shutdown(status, "post-exit package-host frame quiescence")
    observed_frame_count = status.get("framesPresented")
    if type(observed_frame_count) is not int or observed_frame_count < 1:
        raise M0Error("post-exit package-host frame count is invalid")
    if observed_frame_count != expected_frame_count:
        raise M0Error("package host presented a frame after clean shutdown")


def _observe_post_exit_frame_quiescence(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    clean_shutdown: dict[str, Any],
    expected_url: str,
    expected_epoch: str,
    expected_package_metadata: dict[str, object],
    expected_time_origin: float,
    expected_wisp_configured: bool,
    description: str,
) -> None:
    """Observe a fixed, same-document post-exit canvas quiet interval.

    The checked host status is deliberately limited to the existing
    frame-presentation counter and verified terminal lifecycle signals. It is
    not a descriptor drain, worker census, transport teardown, or leak check.
    """

    expected_frame_count = clean_shutdown.get("framesPresented")
    if type(expected_frame_count) is not int or expected_frame_count < 1:
        raise M0Error("post-exit package-host frame count is invalid")
    _require_post_exit_frame_quiescence_sample(clean_shutdown, expected_frame_count)
    _require_terminal_package_document(
        clean_shutdown,
        expected_url=expected_url,
        expected_epoch=expected_epoch,
        expected_package_metadata=expected_package_metadata,
        expected_time_origin=expected_time_origin,
    )
    _require_release_wisp_configuration(clean_shutdown, expected_wisp_configured)

    quiescence_deadline = time.monotonic() + POST_EXIT_FRAME_QUIESCENCE_SECONDS
    if quiescence_deadline >= deadline:
        raise M0Error("package post-exit frame quiescence does not fit before timeout")

    def is_quiescent(status: dict[str, Any]) -> bool:
        _require_post_exit_frame_quiescence_sample(status, expected_frame_count)
        _require_terminal_package_document(
            status,
            expected_url=expected_url,
            expected_epoch=expected_epoch,
            expected_package_metadata=expected_package_metadata,
            expected_time_origin=expected_time_origin,
        )
        _require_release_wisp_configuration(status, expected_wisp_configured)
        return time.monotonic() >= quiescence_deadline

    # The shared status poll sleeps for at most 50 ms between samples. Permit
    # one extra interval to evaluate the predicate at or after the exact
    # 100 ms boundary rather than mistaking scheduler jitter for a timeout.
    _wait_for_status(
        client=client,
        browser=browser,
        browser_stderr=browser_stderr,
        deadline=min(deadline, quiescence_deadline + 0.05),
        predicate=is_quiescent,
        description=description,
    )


def _restart_after_clean_shutdown(
    *,
    client: Any,
    clean_shutdown: dict[str, Any],
    restart_url: str,
    debug_port: int,
    deadline: float,
    release_wisp_endpoint: str | None = None,
) -> Any:
    """Navigate only after a verified first host shutdown and reattach CDP."""

    _require_clean_shutdown(clean_shutdown, "first fixed package-host shutdown")
    try:
        if release_wisp_endpoint is not None:
            _install_release_wisp_configuration(client, release_wisp_endpoint)
        _navigate_to_package_document(client, restart_url)
    finally:
        # A navigation invalidates the first document's observation channel.
        # Always close it before asking DevTools for the exact fresh target.
        client.close()
    return wait_for_page_client(debug_port, restart_url, deadline)


def _fatal_record(status: dict[str, Any]) -> str | None:
    records = status.get("records")
    if not isinstance(records, list):
        return None
    for record in records:
        if isinstance(record, dict) and record.get("kind") == "fatal":
            return str(record.get("value", "unknown host fatal"))
    return None


def _has_zero_fatal_count(status: dict[str, Any]) -> bool:
    """Require the host's fixed health signal, not bounded record retention."""

    return type(status.get("fatalCount")) is int and status["fatalCount"] == 0


def _validate_fatal_health(status: dict[str, Any]) -> None:
    """Reject missing, malformed, or nonzero sticky fatal-health evidence."""

    count = status.get("fatalCount")
    if type(count) is not int or not 0 <= count <= MAX_SAFE_INTEGER:
        raise M0Error("package host fatal count is invalid")
    if count != 0:
        fatal = _fatal_record(status)
        if fatal is not None:
            raise M0Error(f"package host reported fatal: {fatal}")
        raise M0Error(f"package host reported {count} fatal errors")


def _is_ready(status: dict[str, Any]) -> bool:
    readiness = status.get("readiness")
    displayed_versions = status.get("displayedVersions")
    return (
        _has_zero_fatal_count(status)
        and status.get("crossOriginIsolated") is True
        and status.get("releaseStatus") == RELEASE_STATUS
        and status.get("runtimeArtifactsVerified") is True
        and status.get("runtimeInitialized") is True
        and type(status.get("framesPresented")) is int
        and status["framesPresented"] >= 1
        and isinstance(readiness, dict)
        and readiness.get("surfaceReady") is True
        and status.get("pageState") == "running"
        and isinstance(displayed_versions, str)
        and "staging checkout" in displayed_versions
        and "artifact source provenance" in displayed_versions
        and (
            "unverified" in displayed_versions
            or "local_clean_build_attested" in displayed_versions
        )
    )


def _wait_for_status(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    predicate: Any,
    description: str,
) -> dict[str, Any]:
    last_status: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                f"host browser exited while {description} (status "
                f"{browser.returncode}): " + "\n".join(browser_stderr)
            )
        status = _status(client)
        last_status = status
        if status.get("pageError"):
            raise M0Error(f"package host page error: {status['pageError']}")
        # The CDP attachment can observe a staged document before its host
        # elements/status JSON exist. That explicit transient has no health
        # payload yet; once a status payload is available, health is strict.
        if status.get("pending") is not True:
            _validate_fatal_health(status)
        fatal = _fatal_record(status)
        if fatal is not None:
            raise M0Error(f"package host reported fatal: {fatal}")
        if predicate(status):
            return status
        time.sleep(0.05)
    raise M0Error(
        f"timed out while {description}: "
        + json.dumps(last_status, sort_keys=True, default=str)
    )


def _wait_for_ready_package_document(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    expected_url: str,
    expected_epoch: str,
    expected_package_metadata: dict[str, object],
    prior_time_origin: float | None,
    description: str,
    expected_wisp_configured: bool = False,
) -> tuple[dict[str, Any], float]:
    ready = _wait_for_status(
        client=client,
        browser=browser,
        browser_stderr=browser_stderr,
        deadline=deadline,
        predicate=_is_ready,
        description=description,
    )
    _require_release_wisp_configuration(ready, expected_wisp_configured)
    return (
        ready,
        _require_ready_package_document(
            ready,
            expected_url=expected_url,
            expected_epoch=expected_epoch,
            expected_package_metadata=expected_package_metadata,
            prior_time_origin=prior_time_origin,
        ),
    )


def _request_clean_shutdown(
    *,
    client: Any,
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    deadline: float,
    expected_url: str,
    expected_epoch: str,
    expected_package_metadata: dict[str, object],
    expected_time_origin: float,
    description: str,
) -> dict[str, Any]:
    client.evaluate('document.querySelector("#shutdown").click(); true')
    clean_shutdown = _wait_for_status(
        client=client,
        browser=browser,
        browser_stderr=browser_stderr,
        deadline=deadline,
        predicate=_is_clean_shutdown,
        description=description,
    )
    _require_clean_shutdown(clean_shutdown, description)
    _require_terminal_package_document(
        clean_shutdown,
        expected_url=expected_url,
        expected_epoch=expected_epoch,
        expected_package_metadata=expected_package_metadata,
        expected_time_origin=expected_time_origin,
    )
    return clean_shutdown


def _epoch_result(
    ready: dict[str, Any],
    clean_shutdown: dict[str, Any],
    *,
    post_exit_frame_quiescent: bool = False,
    runtime_core_resource_receipt: list[dict[str, str]] | None = None,
    runtime_core_server_receipt: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    _require_clean_shutdown(clean_shutdown, "package-host shutdown")
    result: dict[str, object] = {
        "frames_presented": ready["framesPresented"],
        "runtime_exit_code": clean_shutdown["runtimeExitCode"],
        "process_exit_code": clean_shutdown["processExitCode"],
        "shutdown_disabled": clean_shutdown["shutdownDisabled"],
        "shutdown_requested": clean_shutdown["shutdownRequested"],
    }
    if post_exit_frame_quiescent:
        result["post_exit_frame_quiescent"] = True
    if runtime_core_resource_receipt is not None:
        result["runtime_core_resource_receipt"] = (
            validate_runtime_core_resource_receipt(runtime_core_resource_receipt)
        )
    if runtime_core_server_receipt is not None:
        result["runtime_core_server_receipt"] = validate_runtime_core_server_receipt(
            runtime_core_server_receipt
        )
    return result


def _run_cleanup_action(
    cleanup_error: BaseException | None, action: Callable[[], object]
) -> BaseException | None:
    """Runs one cleanup action without preventing the remaining cleanup."""

    try:
        action()
    except BaseException as exc:
        if cleanup_error is None:
            return exc
    return cleanup_error


def _join_package_browser_server(thread: threading.Thread) -> None:
    """Joins a started package server and rejects an incomplete teardown."""

    thread.join(timeout=5)
    if thread.is_alive():
        raise M0Error("M9 package browser server did not stop")


def run_package_browser_smoke(
    *,
    dist_dir: Path,
    browser_argument: Path | None,
    no_sandbox: bool,
    timeout: float,
    outer_document_restart: bool = False,
    outer_document_restart_count: int = 0,
    release_wisp_endpoint: str | None = None,
    emit_package_observation: bool = False,
) -> dict[str, object]:
    server = None
    server_thread = None
    server_thread_started = False
    browser: subprocess.Popen[str] | None = None
    stderr_reader: BrowserStderrReader | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    client: Any = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    primary_error: BaseException | None = None
    try:
        if type(outer_document_restart) is not bool:
            raise M0Error("package outer-document restart selection is invalid")
        if (
            type(outer_document_restart_count) is not int
            or not 0 <= outer_document_restart_count <= MAX_OUTER_DOCUMENT_RESTARTS
        ):
            raise M0Error("package outer-document restart count is invalid")
        if outer_document_restart and outer_document_restart_count not in (0, 1):
            raise M0Error(
                "package outer-document restart selection and count disagree"
            )
        restart_count = 1 if outer_document_restart else outer_document_restart_count
        observe_runtime_core_resource_receipt = (
            restart_count == OUTER_DOCUMENT_RELOAD_STRESS_RESTART_COUNT
        )
        if type(emit_package_observation) is not bool:
            raise M0Error("package observation selection is invalid")
        if emit_package_observation and release_wisp_endpoint is not None:
            raise M0Error(
                "package startup observation requires the default WISP-disabled path"
            )
        if release_wisp_endpoint is not None:
            release_wisp_endpoint = _normalize_release_wisp_endpoint(
                release_wisp_endpoint
            )
        browser_path, browser_version = find_browser(browser_argument)
        server = create_package_smoke_server("127.0.0.1", 0, dist_dir)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m9-package-browser-server",
            daemon=True,
        )
        server_thread.start()
        server_thread_started = True
        expected_package_metadata = _runtime_metadata_from_server_snapshot(server)
        host, port = server.server_address[:2]
        package_url = f"http://{host}:{port}/"
        first_epoch = secrets.token_urlsafe(18)
        first_url = (
            _register_epoch_document_url(server, package_url, first_epoch)
            if observe_runtime_core_resource_receipt
            else _make_epoch_url(package_url, first_epoch)
        )
        profile = tempfile.TemporaryDirectory(prefix="chromium-wasm-m9-package-")
        debug_port = unused_loopback_port()
        launch_url = (
            WISP_BOOTSTRAP_URL
            if release_wisp_endpoint is not None
            else first_url
        )
        command = browser_command(
            browser_path, profile.name, launch_url, no_sandbox=no_sandbox
        )
        command[1:1] = [
            "--enable-logging=stderr",
            "--remote-allow-origins=http://localhost",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
        ]
        launch_started_at = time.monotonic() if emit_package_observation else None
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
            name="chromium-wasm-m9-package-browser-stderr",
            thread_factory=threading.Thread,
        )
        stderr_reader.start()
        deadline = time.monotonic() + timeout
        client = wait_for_page_client(debug_port, launch_url, deadline)
        if release_wisp_endpoint is not None:
            _install_release_wisp_configuration(client, release_wisp_endpoint)
            _navigate_to_package_document(client, first_url)
        first_ready, first_time_origin = _wait_for_ready_package_document(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_url=first_url,
            expected_epoch=first_epoch,
            expected_package_metadata=expected_package_metadata,
            prior_time_origin=None,
            expected_wisp_configured=release_wisp_endpoint is not None,
            description="waiting for the first real package frame",
        )
        first_runtime_core_resource_receipt = (
            _capture_runtime_core_resource_receipt(
                client, expected_url=first_url
            )
            if observe_runtime_core_resource_receipt
            else None
        )
        package_observation = (
            _package_startup_observation(
                server=server,
                ready=first_ready,
                launch_started_at=launch_started_at,
            )
            if emit_package_observation
            else None
        )
        first_shutdown = _request_clean_shutdown(
            client=client,
            browser=browser,
            browser_stderr=browser_stderr,
            deadline=deadline,
            expected_url=first_url,
            expected_epoch=first_epoch,
            expected_package_metadata=expected_package_metadata,
            expected_time_origin=first_time_origin,
            description="waiting for the first clean fixed package-host shutdown",
        )
        observe_post_exit_frame_quiescence = (
            restart_count == OUTER_DOCUMENT_RELOAD_STRESS_RESTART_COUNT
        )
        if observe_post_exit_frame_quiescence:
            _observe_post_exit_frame_quiescence(
                client=client,
                browser=browser,
                browser_stderr=browser_stderr,
                deadline=deadline,
                clean_shutdown=first_shutdown,
                expected_url=first_url,
                expected_epoch=first_epoch,
                expected_package_metadata=expected_package_metadata,
                expected_time_origin=first_time_origin,
                expected_wisp_configured=release_wisp_endpoint is not None,
                description=(
                    "observing post-exit package-host frame quiescence "
                    "for fixed outer-document lifetime 1"
                ),
            )
        first_runtime_core_server_receipt = (
            _capture_runtime_core_server_receipt(server, epoch=first_epoch)
            if observe_runtime_core_resource_receipt
            else None
        )
        first_result = _epoch_result(
            first_ready,
            first_shutdown,
            post_exit_frame_quiescent=observe_post_exit_frame_quiescence,
            runtime_core_resource_receipt=first_runtime_core_resource_receipt,
            runtime_core_server_receipt=first_runtime_core_server_receipt,
        )
        if restart_count == 0:
            result = {
                "browser_version": browser_version,
                "frames_presented": first_result["frames_presented"],
                "runtime_exit_code": first_result["runtime_exit_code"],
                "process_exit_code": first_result["process_exit_code"],
                "release_status": first_ready["releaseStatus"],
                "scope": SCOPE,
                "served_version_json_sha256": expected_package_metadata[
                    "versionJsonSha256"
                ],
                "shutdown_disabled": first_result["shutdown_disabled"],
                "shutdown_requested": first_result["shutdown_requested"],
            }
            if package_observation is not None:
                result["package_observation"] = package_observation
            if release_wisp_endpoint is not None:
                result["release_wisp_pre_navigation_configured"] = True
            return result

        epoch_results = [first_result]
        seen_epochs = {first_epoch}
        seen_time_origins = {first_time_origin}
        prior_shutdown = first_shutdown
        prior_time_origin = first_time_origin
        for restart_index in range(1, restart_count + 1):
            epoch = secrets.token_urlsafe(18)
            if epoch in seen_epochs:
                raise M0Error("package restart document epoch was reused")
            seen_epochs.add(epoch)
            restart_url = (
                _register_epoch_document_url(server, package_url, epoch)
                if observe_runtime_core_resource_receipt
                else _make_epoch_url(package_url, epoch)
            )
            client = _restart_after_clean_shutdown(
                client=client,
                clean_shutdown=prior_shutdown,
                restart_url=restart_url,
                debug_port=debug_port,
                deadline=deadline,
                release_wisp_endpoint=release_wisp_endpoint,
            )
            ready, time_origin = _wait_for_ready_package_document(
                client=client,
                browser=browser,
                browser_stderr=browser_stderr,
                deadline=deadline,
                expected_url=restart_url,
                expected_epoch=epoch,
                expected_package_metadata=expected_package_metadata,
                prior_time_origin=prior_time_origin,
                expected_wisp_configured=release_wisp_endpoint is not None,
                description=(
                    "waiting for fresh outer-document package frame "
                    f"{restart_index + 1}"
                ),
            )
            if time_origin in seen_time_origins:
                raise M0Error("package restart document time origin was reused")
            seen_time_origins.add(time_origin)
            runtime_core_resource_receipt = (
                _capture_runtime_core_resource_receipt(
                    client, expected_url=restart_url
                )
                if observe_runtime_core_resource_receipt
                else None
            )
            shutdown = _request_clean_shutdown(
                client=client,
                browser=browser,
                browser_stderr=browser_stderr,
                deadline=deadline,
                expected_url=restart_url,
                expected_epoch=epoch,
                expected_package_metadata=expected_package_metadata,
                expected_time_origin=time_origin,
                description=(
                    "waiting for clean fixed package-host shutdown "
                    f"{restart_index + 1}"
                ),
            )
            if observe_post_exit_frame_quiescence:
                _observe_post_exit_frame_quiescence(
                    client=client,
                    browser=browser,
                    browser_stderr=browser_stderr,
                    deadline=deadline,
                    clean_shutdown=shutdown,
                    expected_url=restart_url,
                    expected_epoch=epoch,
                    expected_package_metadata=expected_package_metadata,
                    expected_time_origin=time_origin,
                    expected_wisp_configured=release_wisp_endpoint is not None,
                    description=(
                        "observing post-exit package-host frame quiescence "
                        f"for fixed outer-document lifetime {restart_index + 1}"
                    ),
                )
            runtime_core_server_receipt = (
                _capture_runtime_core_server_receipt(server, epoch=epoch)
                if observe_runtime_core_resource_receipt
                else None
            )
            epoch_results.append(
                _epoch_result(
                    ready,
                    shutdown,
                    post_exit_frame_quiescent=observe_post_exit_frame_quiescence,
                    runtime_core_resource_receipt=runtime_core_resource_receipt,
                    runtime_core_server_receipt=runtime_core_server_receipt,
                )
            )
            prior_shutdown = shutdown
            prior_time_origin = time_origin

        if restart_count == 1:
            result = {
                "browser_version": browser_version,
                "epochs": epoch_results,
                "outer_document_restart": True,
                "release_status": first_ready["releaseStatus"],
                "scope": OUTER_DOCUMENT_RESTART_SCOPE,
                "served_version_json_sha256": expected_package_metadata[
                    "versionJsonSha256"
                ],
            }
            if package_observation is not None:
                result["package_observation"] = package_observation
            if release_wisp_endpoint is not None:
                result["release_wisp_pre_navigation_configured"] = True
            return result

        result = {
            "browser_version": browser_version,
            "distinct_document_epoch_count": len(seen_epochs),
            "distinct_document_time_origin_count": len(seen_time_origins),
            "epochs": epoch_results,
            "limitations": list(OUTER_DOCUMENT_RELOAD_STRESS_LIMITATIONS),
            "m9_gate_complete": False,
            "outer_document_epoch_count": len(epoch_results),
            "outer_document_restarts": restart_count,
            "performance_gate": False,
            "release_status": first_ready["releaseStatus"],
            "scope": OUTER_DOCUMENT_RELOAD_STRESS_SCOPE,
            "served_version_json_sha256": expected_package_metadata[
                "versionJsonSha256"
            ],
        }
        if package_observation is not None:
            result["package_observation"] = package_observation
        if release_wisp_endpoint is not None:
            result["release_wisp_pre_navigation_configured"] = True
        return result
    except BaseException as exc:
        primary_error = exc
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
            # This can only be a startup-failure path.  It still needs to
            # terminate the dedicated session, not merely the browser leader.
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: abort_browser_group(browser, stderr_reader)
            )
        if server is not None:
            if server_thread_started:
                cleanup_error = _run_cleanup_action(
                    cleanup_error,
                    lambda: shutdown_server_bounded(
                        server, timeout=5, description="M9 package browser server"
                    ),
                )
            cleanup_error = _run_cleanup_action(cleanup_error, server.server_close)
        if server_thread_started and server_thread is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error, lambda: _join_package_browser_server(server_thread)
            )
        if server is not None:
            cleanup_error = _run_cleanup_action(
                cleanup_error,
                lambda: server.join_request_handlers(
                    timeout=5, description="M9 package browser server"
                ),
            )
        if profile is not None:
            cleanup_error = _run_cleanup_action(cleanup_error, profile.cleanup)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Boot a staged pre-release Chromium Wasm package in Chrome."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument(
        "--release-wisp-endpoint",
        help=(
            "install one credential-free wss: carrier endpoint through CDP "
            "before each package document; this does not test live WISP traffic"
        ),
    )
    parser.add_argument(
        "--outer-document-restart",
        action="store_true",
        help=(
            "after one clean package-host shutdown, navigate the outer document "
            "to a fresh package epoch and require a second clean lifetime"
        ),
    )
    parser.add_argument(
        "--emit-package-observation",
        action="store_true",
        help=(
            "emit one explicitly non-gating fresh-browser package startup and "
            "raw-snapshot-byte observation; default smoke output is unchanged"
        ),
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()
    if args.timeout < 10:
        parser.error("--timeout must allow package startup and shutdown")
    if args.outer_document_restart and args.timeout < 20:
        parser.error("--outer-document-restart requires two package lifetimes")
    if args.emit_package_observation and args.release_wisp_endpoint is not None:
        parser.error(
            "--emit-package-observation requires the default WISP-disabled path"
        )
    try:
        result = run_package_browser_smoke(
            dist_dir=args.dist_dir,
            browser_argument=args.browser,
            no_sandbox=args.no_sandbox,
            timeout=args.timeout,
            outer_document_restart=args.outer_document_restart,
            outer_document_restart_count=0,
            release_wisp_endpoint=args.release_wisp_endpoint,
            emit_package_observation=args.emit_package_observation,
        )
        print(
            f"{SENTINEL}:BROWSER_SMOKE_PASS "
            + json.dumps(result, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        return 0
    except (M0Error, OSError, TypeError, ValueError) as exc:
        print(f"{SENTINEL}:BROWSER_SMOKE_FAIL reason={exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

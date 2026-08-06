#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run one opt-in public HTTPS probe through Chromium and an external WISP.

This deliberately does not reuse the controlled M5 relay. An operator supplies
an uncredentialed WSS gateway and one project-controlled public HTTPS document
at invocation time. Neither value is a default, is committed, or is written to
the runner's result and diagnostics. The gateway must independently allow only
the exact public DNS hostname on TCP port 443.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import ipaddress
import json
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import quote, quote_plus, unquote, urlencode, urlsplit, urlunsplit

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    load_manifest,
    parse_timeout,
    print_context,
)
from m3_content_server import (
    M3_HOST_DIR,
    M3_HOST_SNAPSHOT_PATHS,
    M5_PUBLIC_HTTPS_CASE,
    create_m3_server,
)
from run_browser_smoke import (
    browser_command,
    drain_stream,
    find_browser,
    stop_browser,
)
from run_content_shell_smoke import manifest_versions
from run_m5_wisp_smoke import verify_no_private_key_pem_artifacts


SENTINEL = "CHROMIUM_WASM_M5_PUBLIC_HTTPS"
PUBLIC_PROVENANCE_PROTOCOL = 2
PUBLIC_PROVENANCE_VERSION_KEYS = frozenset(
    ("chromium", "v8", "emscripten", "port")
)
DEFAULT_MODULE_NAME = "content_shell_wasm_m5_public_test"
PUBLIC_ARTIFACT_PROVENANCE_KEYS = frozenset(
    (
        "argsGnSha256",
        "hostHtml",
        "hostJavaScript",
        "javascript",
        "module",
        "wasm",
    )
)
PUBLIC_ARTIFACT_FILE_KEYS = frozenset(("sha256", "size"))
PUBLIC_PROVENANCE_MAXIMUM_BYTES = 4096
MAXIMUM_URL_BYTES = 2048
M5_PUBLIC_GATEWAY_DENIED_PORT = 444
M5_PUBLIC_GATEWAY_DENIED_PATH = "/.well-known/chromium-wasm-m5-wisp-denied"
MAXIMUM_TIMER_GAP_MS = 250
MINIMUM_HEARTBEAT_TIMER_TICKS = 2
MINIMUM_HEARTBEAT_ANIMATION_FRAMES = 2
BROWSER_WINDOW_SIZE = "1280,800"
PUBLIC_SPECIAL_USE_HOSTNAME_SUFFIXES = (
    ".localhost",
    ".local",
    ".test",
    ".example",
    ".invalid",
    ".onion",
    ".home.arpa",
)
URL_LIKE_VALUE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?:https?|wss)(?:://|:%2f%2f|:%252f%252f|%3a%2f%2f|%253a%252f%252f)"
    r"|//"
    r")[^\s\"'<>]*",
    re.IGNORECASE,
)
URL_REDACTION_ENCODING_DEPTH = 2
PUBLIC_DEVTOOLS_NETWORK_EVENTS = (
    "Network.requestWillBeSent:document",
    "Network.responseReceived:document",
    "Network.loadingFinished:document",
)


def _is_safe_public_url_string(value: str) -> bool:
    """Keep runtime-only URLs safe for argv, query, and redaction boundaries."""

    return value.isascii() and all("!" <= character <= "~" for character in value)


def _validated_port(parsed: Any, description: str) -> int | None:
    try:
        port = parsed.port
    except ValueError as exc:
        raise M0Error(f"{description} has an invalid port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise M0Error(f"{description} has an invalid port")
    return port


def _split_public_url(value: str, description: str) -> Any:
    try:
        return urlsplit(value)
    except ValueError as exc:
        raise M0Error(f"{description} is not a valid URL") from exc


def _is_public_dns_hostname(hostname: str) -> bool:
    """Reject literals and local-only DNS names before they reach a gateway."""

    normalized = hostname.lower()
    if (
        not normalized
        or not normalized.isascii()
        or normalized == "localhost"
        or normalized == "home.arpa"
        or normalized.endswith(".")
        or any(
            normalized.endswith(suffix)
            for suffix in PUBLIC_SPECIAL_USE_HOSTNAME_SUFFIXES
        )
        or "." not in normalized
    ):
        return False
    try:
        ipaddress.ip_address(normalized)
        return False
    except ValueError:
        pass
    labels = normalized.split(".")
    if not all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        return False
    # WHATWG URL parsing canonicalizes legacy IPv4 spellings such as 127.1,
    # 0177.0.0.1, and 0x7f.0x0.0x0.0x1 to 127.0.0.1. Reject every
    # all-numeric component form conservatively before the browser turns a
    # seemingly public WSS hostname into a loopback literal.
    def is_legacy_ipv4_component(label: str) -> bool:
        if label.startswith("0x"):
            return len(label) > 2 and all(
                character in "0123456789abcdef" for character in label[2:]
            )
        return label.isdecimal()

    return not (
        len(labels) <= 4
        and all(is_legacy_ipv4_component(label) for label in labels)
    )


def _has_noncanonical_path(path: str) -> bool:
    decoded_path = unquote(path)
    return (
        "\\" in decoded_path
        or any(
            not character.isascii() or not "!" <= character <= "~"
            for character in decoded_path
        )
        or any(
            component in (".", "..")
            for component in decoded_path.split("/")
        )
    )


def _canonical_public_url(
    parsed: Any, *, scheme: str, port: int | None, default_port: int
) -> str:
    assert parsed.hostname is not None
    netloc = parsed.hostname.lower()
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path, "", ""))


def _url_redaction_variants(value: str) -> tuple[str, ...]:
    """Return URL, hostname, and bounded escaped forms of a public input."""

    if not value:
        return ()
    forms = {value}
    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.scheme and parsed.netloc:
        raw_authority = parsed.netloc.rsplit("@", maxsplit=1)[-1]
        if raw_authority:
            forms.add(raw_authority)
        forms.add(
            urlunsplit(
                ("", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
            )
        )
        if parsed.hostname:
            hostname = parsed.hostname
            forms.add(hostname)
            default_port = 443 if parsed.scheme in ("https", "wss") else None
            try:
                port = parsed.port
            except ValueError:
                port = None
            if port is not None:
                forms.add(f"{hostname}:{port}")
            elif default_port is not None:
                # Browser/network diagnostics may make a default TLS port
                # explicit even when it was omitted in the input URL.
                forms.add(f"{hostname}:{default_port}")
                if raw_authority:
                    forms.add(f"{raw_authority}:{default_port}")

    variants: set[str] = set()
    for form in forms:
        frontier = {form}
        for depth in range(URL_REDACTION_ENCODING_DEPTH + 1):
            variants.update(frontier)
            if depth == URL_REDACTION_ENCODING_DEPTH:
                break
            encoded: set[str] = set()
            for candidate in frontier:
                try:
                    encoded.add(quote(candidate, safe=""))
                    encoded.add(quote_plus(candidate, safe=""))
                except UnicodeError:
                    continue
            frontier = encoded
    return tuple(sorted(variants, key=len, reverse=True))


def _configured_public_url_variants(*values: str) -> tuple[str, ...]:
    """Collect every bounded URL and authority form of runtime-only inputs."""

    candidates = set(values)
    for value in values:
        try:
            candidates.add(validate_public_wisp_endpoint(value))
        except M0Error:
            pass
        try:
            probe_url = validate_public_probe_url(value)
            candidates.add(probe_url)
            candidates.add(_public_gateway_denied_url(probe_url))
        except M0Error:
            pass
    variants: set[str] = set()
    for candidate in candidates:
        variants.update(_url_redaction_variants(candidate))
    return tuple(sorted(variants, key=len, reverse=True))


def validate_public_wisp_endpoint(value: object) -> str:
    """Accept one credential-free external WSS endpoint, never a local relay."""

    if not isinstance(value, str) or not value:
        raise M0Error("public WISP endpoint must be a nonempty string")
    if not _is_safe_public_url_string(value):
        raise M0Error("public WISP endpoint contains unsupported characters")
    if len(value.encode("utf-8")) > MAXIMUM_URL_BYTES:
        raise M0Error("public WISP endpoint is too long")
    parsed = _split_public_url(value, "public WISP endpoint")
    port = _validated_port(parsed, "public WISP endpoint")
    if (
        parsed.scheme != "wss"
        or not parsed.hostname
        or not _is_public_dns_hostname(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or not parsed.path.endswith("/")
        or _has_noncanonical_path(parsed.path)
    ):
        raise M0Error("public WISP endpoint violates the external policy")
    return _canonical_public_url(
        parsed, scheme="wss", port=port, default_port=443
    )


def validate_public_probe_url(value: object) -> str:
    """Accept a canonical public HTTPS document on the default TLS port."""

    if not isinstance(value, str) or not value:
        raise M0Error("public HTTPS probe URL must be a nonempty string")
    if not _is_safe_public_url_string(value):
        raise M0Error("public HTTPS probe URL contains unsupported characters")
    if len(value.encode("utf-8")) > MAXIMUM_URL_BYTES:
        raise M0Error("public HTTPS probe URL is too long")
    parsed = _split_public_url(value, "public HTTPS probe URL")
    port = _validated_port(parsed, "public HTTPS probe URL")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not _is_public_dns_hostname(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
        or not parsed.path.startswith("/")
        or _has_noncanonical_path(parsed.path)
    ):
        raise M0Error("public HTTPS probe URL violates the public-probe policy")
    return _canonical_public_url(
        parsed, scheme="https", port=port, default_port=443
    )


def _public_gateway_denied_url(value: str) -> str:
    """Derive the native same-host denied preflight from a public probe."""

    probe_url = validate_public_probe_url(value)
    parsed = _split_public_url(probe_url, "public HTTPS probe URL")
    if not parsed.hostname:
        raise M0Error("public HTTPS probe URL has no hostname")
    return urlunsplit(
        (
            "https",
            f"{parsed.hostname}:{M5_PUBLIC_GATEWAY_DENIED_PORT}",
            M5_PUBLIC_GATEWAY_DENIED_PATH,
            "",
            "",
        )
    )


def parse_expected_status(value: str) -> int:
    try:
        status = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "expected HTTP status must be an integer"
        ) from exc
    if not 100 <= status <= 599:
        raise argparse.ArgumentTypeError(
            "expected HTTP status must be in [100, 599]"
        )
    return status


def public_smoke_url(
    server: Any,
    token: str,
    versions: dict[str, str],
    *,
    public_wisp_endpoint: str,
    public_probe_url: str,
    expected_status: int,
    expected_protocol: str,
    module_name: str = DEFAULT_MODULE_NAME,
    timeout_seconds: float = 120.0,
) -> str:
    """Build the local host URL without logging the supplied public inputs."""

    endpoint = validate_public_wisp_endpoint(public_wisp_endpoint)
    probe_url = validate_public_probe_url(public_probe_url)
    if type(expected_protocol) is not str or expected_protocol not in (
        "h2",
        "http/1.1",
    ):
        raise M0Error("public HTTPS expected protocol is invalid")
    if type(expected_status) is not int or not 100 <= expected_status <= 599:
        raise M0Error("public HTTPS expected status is invalid")
    host, port = server.server_address[:2]
    query = urlencode(
        {
            "case": M5_PUBLIC_HTTPS_CASE,
            "chromium": versions["chromium"],
            "emscripten": versions["emscripten"],
            "m5_public_protocol": expected_protocol,
            "m5_public_status": expected_status,
            "m5_public_url": probe_url,
            "module": f"/__m3__/artifacts/{module_name}.js",
            "port": versions["port"],
            "token": token,
            "timeout_ms": max(1000, min(180000, int(timeout_seconds * 1000))),
            "v8": versions["v8"],
            "wisp_endpoint": endpoint,
        }
    )
    return f"http://{host}:{port}/__m3__/?{query}"


def public_browser_command(
    browser: Path, profile: str, url: str, *, no_sandbox: bool
) -> list[str]:
    command = browser_command(browser, profile, url, no_sandbox=no_sandbox)
    command[1:1] = [f"--window-size={BROWSER_WINDOW_SIZE}"]
    return command


def _require_dict(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M0Error(f"{description} must be an object")
    return value


def _require_bool(value: object, description: str) -> bool:
    if type(value) is not bool:
        raise M0Error(f"{description} must be a bool")
    return value


def _require_int(value: object, description: str) -> int:
    if type(value) is not int:
        raise M0Error(f"{description} must be an int")
    return value


def _require_string(value: object, description: str) -> str:
    if type(value) is not str:
        raise M0Error(f"{description} must be a string")
    return value


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


def _is_lower_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validated_public_artifact_file(
    value: object, description: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != PUBLIC_ARTIFACT_FILE_KEYS:
        raise M0Error(f"{description} has an invalid schema")
    size = value["size"]
    if type(size) is not int or size <= 0:
        raise M0Error(f"{description} size is invalid")
    if not _is_lower_sha256(value["sha256"]):
        raise M0Error(f"{description} SHA-256 is invalid")
    return {"sha256": value["sha256"], "size": size}


def validate_public_artifact_provenance(artifacts: object) -> dict[str, Any]:
    """Validate the fixed module identity safe to retain in public reports."""

    if type(artifacts) is not dict or set(artifacts) != (
        PUBLIC_ARTIFACT_PROVENANCE_KEYS
    ):
        raise M0Error("public HTTPS artifact provenance has an invalid schema")
    if artifacts["module"] != DEFAULT_MODULE_NAME:
        raise M0Error("public HTTPS artifact provenance module is invalid")
    if not _is_lower_sha256(artifacts["argsGnSha256"]):
        raise M0Error("public HTTPS artifact provenance GN args hash is invalid")
    return {
        "argsGnSha256": artifacts["argsGnSha256"],
        "hostHtml": _validated_public_artifact_file(
            artifacts["hostHtml"], "public HTTPS host HTML"
        ),
        "hostJavaScript": _validated_public_artifact_file(
            artifacts["hostJavaScript"], "public HTTPS host JavaScript"
        ),
        "javascript": _validated_public_artifact_file(
            artifacts["javascript"], "public HTTPS JavaScript artifact"
        ),
        "module": artifacts["module"],
        "wasm": _validated_public_artifact_file(
            artifacts["wasm"], "public HTTPS Wasm artifact"
        ),
    }


def _public_artifact_path(out_dir: Path, artifact_name: str) -> Path:
    resolved_out_dir = out_dir.resolve()
    artifact = resolved_out_dir / artifact_name
    if (
        artifact.is_symlink()
        or not artifact.is_file()
        or artifact.resolve().parent != resolved_out_dir
    ):
        raise M0Error(f"public HTTPS artifact {artifact_name} is unavailable")
    return artifact


def _public_host_path(host_name: str) -> Path:
    resolved_host_dir = M3_HOST_DIR.resolve()
    host_path = resolved_host_dir / host_name
    if (
        host_path.is_symlink()
        or not host_path.is_file()
        or host_path.resolve().parent != resolved_host_dir
    ):
        raise M0Error(f"public HTTPS host file {host_name} is unavailable")
    return host_path


def _public_artifact_record(contents: bytes) -> dict[str, Any]:
    if not contents:
        raise M0Error("public HTTPS artifact is empty")
    return {
        "sha256": hashlib.sha256(contents).hexdigest(),
        "size": len(contents),
    }


def _public_args_gn_sha256(out_dir: Path) -> str:
    args_gn = _public_artifact_path(out_dir, "args.gn")
    contents = args_gn.read_bytes()
    if not contents:
        raise M0Error("public HTTPS GN args are empty")
    return hashlib.sha256(contents).hexdigest()


def public_artifact_provenance(
    out_dir: Path, module_name: str = DEFAULT_MODULE_NAME
) -> dict[str, Any]:
    """Hash the exact public module pair without trusting a file timestamp."""

    if module_name != DEFAULT_MODULE_NAME:
        raise M0Error("public HTTPS runner requires its dedicated module")
    return validate_public_artifact_provenance(
        {
            "argsGnSha256": _public_args_gn_sha256(out_dir),
            "hostHtml": _public_artifact_record(
                _public_host_path("content_shell.html").read_bytes()
            ),
            "hostJavaScript": _public_artifact_record(
                _public_host_path("content_shell_host.js").read_bytes()
            ),
            "javascript": _public_artifact_record(
                _public_artifact_path(out_dir, f"{module_name}.js").read_bytes()
            ),
            "module": module_name,
            "wasm": _public_artifact_record(
                _public_artifact_path(out_dir, f"{module_name}.wasm").read_bytes()
            ),
        }
    )


def snapshot_public_artifacts(
    out_dir: Path, module_name: str = DEFAULT_MODULE_NAME
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, bytes]]:
    """Capture the module and host harness bytes this public child will serve.

    The server receives these bytes rather than rereading live output or host
    source files, which binds successful browser execution to the recorded
    digest even if a concurrent build or edit replaces a file mid-run.
    """

    if module_name != DEFAULT_MODULE_NAME:
        raise M0Error("public HTTPS runner requires its dedicated module")
    javascript_name = f"{module_name}.js"
    wasm_name = f"{module_name}.wasm"
    snapshots = {
        javascript_name: _public_artifact_path(out_dir, javascript_name).read_bytes(),
        wasm_name: _public_artifact_path(out_dir, wasm_name).read_bytes(),
    }
    host_html = _public_host_path("content_shell.html").read_bytes()
    host_javascript = _public_host_path("content_shell_host.js").read_bytes()
    static_snapshots = {
        "/": host_html,
        "/__m3__/": host_html,
        "/__m3__/content_shell_host.js": host_javascript,
    }
    if set(static_snapshots) != M3_HOST_SNAPSHOT_PATHS:
        raise M0Error("public HTTPS host snapshot paths are invalid")
    artifacts = validate_public_artifact_provenance(
        {
            "argsGnSha256": _public_args_gn_sha256(out_dir),
            "hostHtml": _public_artifact_record(host_html),
            "hostJavaScript": _public_artifact_record(host_javascript),
            "javascript": _public_artifact_record(snapshots[javascript_name]),
            "module": module_name,
            "wasm": _public_artifact_record(snapshots[wasm_name]),
        }
    )
    return artifacts, snapshots, static_snapshots


def public_provenance(
    versions: object, artifacts: object
) -> dict[str, Any]:
    """Return the fixed build identity record allowed to leave a child run."""

    if (
        type(versions) is not dict
        or set(versions) != PUBLIC_PROVENANCE_VERSION_KEYS
        or any(
            type(versions[key]) is not str or not versions[key]
            for key in PUBLIC_PROVENANCE_VERSION_KEYS
        )
    ):
        raise M0Error("public HTTPS provenance versions are invalid")
    return {
        "artifacts": validate_public_artifact_provenance(artifacts),
        "protocol": PUBLIC_PROVENANCE_PROTOCOL,
        "versions": {
            key: versions[key] for key in sorted(PUBLIC_PROVENANCE_VERSION_KEYS)
        },
    }


def validate_public_provenance(
    provenance: object,
    *,
    expected_versions: object,
    expected_artifacts: object,
) -> dict[str, Any]:
    """Reject an expanded, type-coerced, or stale child provenance record."""

    expected_provenance = public_provenance(
        expected_versions, expected_artifacts
    )
    if type(provenance) is not dict or set(provenance) != {
        "artifacts",
        "protocol",
        "versions",
    }:
        raise M0Error("public HTTPS provenance has an invalid schema")
    if (
        _require_int(provenance["protocol"], "public HTTPS provenance protocol")
        != PUBLIC_PROVENANCE_PROTOCOL
    ):
        raise M0Error("public HTTPS provenance protocol mismatch")
    reported_versions = provenance["versions"]
    if (
        type(reported_versions) is not dict
        or set(reported_versions) != PUBLIC_PROVENANCE_VERSION_KEYS
        or any(
            type(reported_versions[key]) is not str or not reported_versions[key]
            for key in PUBLIC_PROVENANCE_VERSION_KEYS
        )
    ):
        raise M0Error("public HTTPS provenance versions are invalid")
    validate_public_artifact_provenance(provenance["artifacts"])
    if not _exact_json_value_equal(provenance, expected_provenance):
        raise M0Error("public HTTPS provenance mismatch")
    return expected_provenance


def parse_expected_public_provenance(value: object) -> dict[str, Any]:
    """Decode a bounded, duplicate-key-free suite provenance argument."""

    if (
        type(value) is not str
        or not value
        or len(value) > PUBLIC_PROVENANCE_MAXIMUM_BYTES
    ):
        raise M0Error("public HTTPS expected provenance is invalid")

    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, nested_value in pairs:
            if key in result:
                raise ValueError("duplicate public HTTPS provenance key")
            result[key] = nested_value
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise M0Error("public HTTPS expected provenance is invalid") from exc
    if not isinstance(parsed, dict):
        raise M0Error("public HTTPS expected provenance is invalid")
    return parsed


def expected_public_devtools_network_evidence(
    *, expected_status: int, expected_protocol: str
) -> dict[str, Any]:
    """Return the only public-CDP summary that may leave the inner host."""

    if type(expected_status) is not int or not 100 <= expected_status <= 599:
        raise M0Error("public HTTPS expected status is invalid")
    if type(expected_protocol) is not str or expected_protocol not in (
        "h2",
        "http/1.1",
    ):
        raise M0Error("public HTTPS expected protocol is invalid")
    return {
        "protocol": 1,
        "state": "complete",
        "networkEnabled": True,
        "documentRequest": True,
        "responseReceived": True,
        "loadingFinished": True,
        "requestIdCorrelated": True,
        "responseStatus": expected_status,
        "responseProtocol": expected_protocol,
        "wispWebSocketOpened": True,
        "wispHandshakeReady": True,
        "wispConfirmedStream": True,
        "wispDestinationMatched": True,
        "wispDeniedRequest": True,
        "wispDeniedLoadingFailed": True,
        "wispDeniedRequestIdCorrelated": True,
        "wispDeniedByAdministrator": True,
        "events": list(PUBLIC_DEVTOOLS_NETWORK_EVENTS),
    }


def validate_public_devtools_network_evidence(
    evidence: object,
    *,
    expected_status: int,
    expected_protocol: str,
) -> dict[str, Any]:
    """Reject type-coerced or expanded public CDP evidence before comparing."""

    expected_evidence = expected_public_devtools_network_evidence(
        expected_status=expected_status, expected_protocol=expected_protocol
    )
    if type(evidence) is not dict or set(evidence) != set(expected_evidence):
        raise M0Error("public HTTPS DevTools Network log has an invalid schema")
    for field in ("protocol", "responseStatus"):
        if type(evidence[field]) is not int:
            raise M0Error("public HTTPS DevTools Network log has invalid integers")
    for field in (
        "networkEnabled",
        "documentRequest",
        "responseReceived",
        "loadingFinished",
        "requestIdCorrelated",
        "wispWebSocketOpened",
        "wispHandshakeReady",
        "wispConfirmedStream",
        "wispDestinationMatched",
        "wispDeniedRequest",
        "wispDeniedLoadingFailed",
        "wispDeniedRequestIdCorrelated",
        "wispDeniedByAdministrator",
    ):
        if type(evidence[field]) is not bool:
            raise M0Error("public HTTPS DevTools Network log has invalid booleans")
    for field in ("state", "responseProtocol"):
        _require_string(
            evidence[field], "public HTTPS DevTools Network log string field"
        )
    events = evidence["events"]
    if type(events) is not list or any(type(event) is not str for event in events):
        raise M0Error("public HTTPS DevTools Network log has invalid events")
    if evidence != expected_evidence:
        raise M0Error(
            "public HTTPS DevTools Network log does not contain the bounded "
            "Chromium CDP and WISP completion trace"
        )
    return expected_evidence


def public_devtools_network_evidence(
    result: dict[str, Any],
    *,
    expected_status: int,
    expected_protocol: str,
) -> dict[str, Any]:
    """Extract and recheck the fixed, redacted public CDP/WISP evidence."""

    readiness = _require_dict(result.get("readiness"), "public HTTPS readiness")
    return validate_public_devtools_network_evidence(
        readiness.get("publicDevtoolsNetwork"),
        expected_status=expected_status,
        expected_protocol=expected_protocol,
    )


def validate_public_result(
    result: dict[str, Any],
    *,
    expected_versions: dict[str, str],
    expected_status: int,
    expected_protocol: str,
    public_wisp_endpoint: str,
    public_probe_url: str,
) -> None:
    """Validate only redacted public-network evidence from the inner browser."""

    if not isinstance(result, dict):
        raise M0Error("public HTTPS result must be an object")
    validate_public_wisp_endpoint(public_wisp_endpoint)
    validate_public_probe_url(public_probe_url)
    if _require_int(result.get("protocol"), "public HTTPS result protocol") != 1:
        raise M0Error("public HTTPS result protocol mismatch")
    if result.get("case") != M5_PUBLIC_HTTPS_CASE:
        raise M0Error("public HTTPS result case mismatch")
    if result.get("status") != "pass":
        raise M0Error("public HTTPS host reported failure")
    for field in ("crossOriginIsolated", "sharedArrayBuffer", "canvasFocused"):
        if _require_bool(result.get(field), f"public HTTPS {field}") is not True:
            raise M0Error(f"public HTTPS {field} is false")
    if not _exact_json_value_equal(result.get("versions"), expected_versions):
        raise M0Error("public HTTPS versions mismatch")
    initial_frame = _require_dict(
        result.get("initialFrame"), "public HTTPS initial frame"
    )
    initial_frame_id = _require_int(
        initial_frame.get("id"), "public HTTPS initial frame id"
    )
    if (
        initial_frame_id < 1
        or _require_int(
            initial_frame.get("width"), "public HTTPS initial frame width"
        )
        != 800
        or _require_int(
            initial_frame.get("height"), "public HTTPS initial frame height"
        )
        != 600
    ):
        raise M0Error("public HTTPS initial frame is invalid")
    public_frame = _require_dict(
        result.get("publicFrame"), "public HTTPS post-navigation frame"
    )
    public_frame_id = _require_int(
        public_frame.get("id"), "public HTTPS post-navigation frame id"
    )
    if (
        public_frame_id <= initial_frame_id
        or _require_int(
            public_frame.get("width"), "public HTTPS post-navigation frame width"
        )
        != 800
        or _require_int(
            public_frame.get("height"), "public HTTPS post-navigation frame height"
        )
        != 600
    ):
        raise M0Error("public HTTPS post-navigation frame is invalid")
    navigation_result = _require_dict(
        result.get("navigationResult"), "public HTTPS navigation result"
    )
    if not _exact_json_value_equal(
        navigation_result, {"ok": True, "scheme": "https"}
    ):
        raise M0Error("public HTTPS navigation result is invalid")
    public_devtools_network_enabled = _require_dict(
        result.get("publicDevtoolsNetworkEnabled"),
        "public HTTPS DevTools Network enable",
    )
    if not _exact_json_value_equal(
        public_devtools_network_enabled,
        {
            "protocol": 1,
            "state": "enabled",
            "networkEnabled": True,
            "events": [],
        },
    ):
        raise M0Error("public HTTPS DevTools Network.enable is invalid")
    readiness = _require_dict(result.get("readiness"), "public HTTPS readiness")
    navigation = _require_dict(
        readiness.get("navigation"), "public HTTPS navigation evidence"
    )
    if not _exact_json_value_equal(
        navigation,
        {
            "committed": True,
            "scheme": "https",
            "responseCode": expected_status,
            "connectionProtocol": expected_protocol,
        },
    ):
        raise M0Error("public HTTPS navigation metadata is invalid")
    if readiness.get("firstVisuallyNonEmptyPaint") is not True:
        raise M0Error("public HTTPS page did not paint")
    if not _exact_json_value_equal(readiness.get("fatalErrors"), []):
        raise M0Error("public HTTPS readiness reported fatal errors")
    public_devtools_network_evidence(
        result,
        expected_status=expected_status,
        expected_protocol=expected_protocol,
    )
    heartbeat = _require_dict(
        readiness.get("heartbeat"), "public HTTPS host heartbeat"
    )
    if (
        heartbeat.get("anchor") != "m5-public-https-navigation-committed"
        or _require_int(
            heartbeat.get("timerDelta"), "public HTTPS heartbeat timer delta"
        )
        < MINIMUM_HEARTBEAT_TIMER_TICKS
        or _require_int(
            heartbeat.get(
                "animationFrameDelta"
            ),
            "public HTTPS heartbeat animation-frame delta",
        )
        < MINIMUM_HEARTBEAT_ANIMATION_FRAMES
        or _require_int(
            heartbeat.get("maxTimerGapMs"),
            "public HTTPS heartbeat maximum timer gap",
        )
        > MAXIMUM_TIMER_GAP_MS
    ):
        raise M0Error("public HTTPS host heartbeat is invalid")
    logs = _require_dict(result.get("logs"), "public HTTPS logs")
    host_logs = logs.get("host")
    if not isinstance(host_logs, list):
        raise M0Error("public HTTPS host logs must be an array")
    for marker in (
        "initialize:wisp-configured",
        "navigation:requested:data",
        "m5:public-devtools-network:start-requested",
        "m5:public-devtools-network:enabled",
        "navigation:requested:m5-public-https",
        "navigation:committed:m5-public-https",
        "m5:public-devtools-network:complete",
        "shutdown:complete",
    ):
        if host_logs.count(marker) != 1:
            raise M0Error(f"public HTTPS host logs need one {marker!r}")
    if not (
        host_logs.index("initialize:wisp-configured")
        < host_logs.index("navigation:requested:data")
        < host_logs.index("m5:public-devtools-network:start-requested")
        < host_logs.index("m5:public-devtools-network:enabled")
        < host_logs.index("navigation:requested:m5-public-https")
        < host_logs.index("navigation:committed:m5-public-https")
        < host_logs.index("m5:public-devtools-network:complete")
        < host_logs.index("shutdown:complete")
    ):
        raise M0Error("public HTTPS host log ordering is invalid")
    shutdown = _require_dict(result.get("shutdown"), "public HTTPS shutdown")
    if (
        shutdown.get("ok") is not True
        or shutdown.get("complete") is not True
        or _require_int(
            shutdown.get("exitCode"), "public HTTPS shutdown exit code"
        )
        != 0
        or _require_int(
            shutdown.get("runtimeExitCode"),
            "public HTTPS runtime shutdown exit code",
        )
        != 0
    ):
        raise M0Error("public HTTPS shutdown is invalid")
    if (
        not _exact_json_value_equal(result.get("failedChecks"), [])
        or result.get("error") is not None
    ):
        raise M0Error("public HTTPS result contains a failed check")

    # The outer host receives the raw inputs only long enough to configure
    # Emscripten. Do not let them escape back into a result artifact.
    _assert_redacted_public_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True),
        endpoint=public_wisp_endpoint,
        probe_url=public_probe_url,
        description="public HTTPS result",
    )


def wait_for_result(
    browser: subprocess.Popen[str],
    browser_stderr: deque[str],
    result_queue: queue.Queue[dict[str, Any]],
    deadline: float,
) -> dict[str, Any]:
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise M0Error(
                "host browser exited before the public HTTPS result "
                f"(status {browser.returncode})"
            )
        remaining = deadline - time.monotonic()
        try:
            return result_queue.get(timeout=min(0.1, max(0.0, remaining)))
        except queue.Empty:
            continue
    raise M0Error("public HTTPS browser timeout")


def _redact_text(value: str, *, endpoint: str, probe_url: str) -> str:
    result = value
    for rendered in _configured_public_url_variants(endpoint, probe_url):
        result = result.replace(rendered, "<redacted>")
    return URL_LIKE_VALUE_PATTERN.sub("<redacted-url>", result)


def _assert_redacted_public_text(
    value: str,
    *,
    endpoint: str,
    probe_url: str,
    description: str,
) -> None:
    """Ensure no raw public URL, hostname, or URL-like value crosses a boundary."""

    if any(
        rendered in value
        for rendered in _configured_public_url_variants(endpoint, probe_url)
    ):
        raise M0Error(f"{description} leaked a configured public input")
    if URL_LIKE_VALUE_PATTERN.search(value):
        raise M0Error(f"{description} contains an unredacted URL")


def _redact_value(value: Any, *, endpoint: str, probe_url: str) -> Any:
    if isinstance(value, str):
        return _redact_text(value, endpoint=endpoint, probe_url=probe_url)
    if isinstance(value, (list, tuple)):
        return [
            _redact_value(item, endpoint=endpoint, probe_url=probe_url)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            _redact_text(
                str(key), endpoint=endpoint, probe_url=probe_url
            ): _redact_value(
                item, endpoint=endpoint, probe_url=probe_url
            )
            for key, item in value.items()
        }
    return value


def write_failure_diagnostics(
    diagnostics_dir: Path,
    *,
    stage: str,
    error: Exception,
    context: dict[str, object] | None,
    browser_path: Path | None,
    browser_version: str | None,
    browser: subprocess.Popen[str] | None,
    browser_stderr: deque[str],
    result: dict[str, Any] | None,
    public_wisp_endpoint: str,
    public_probe_url: str,
) -> Path:
    """Persist redacted diagnostics without exposing runtime-only URLs."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_path = diagnostics_dir / "m5-public-https-failure.json"
    diagnostic = {
        "schema_version": 1,
        "runner": "run_m5_public_https_smoke.py",
        "case": M5_PUBLIC_HTTPS_CASE,
        "status": "fail",
        "stage": stage,
        "failure": {
            "type": type(error).__name__,
            "message": _redact_text(
                str(error),
                endpoint=public_wisp_endpoint,
                probe_url=public_probe_url,
            ),
        },
        "context": _redact_value(
            context, endpoint=public_wisp_endpoint, probe_url=public_probe_url
        ),
        "configured_inputs": {
            "public_wisp_endpoint": "<redacted>",
            "public_probe_url": "<redacted>",
        },
        "host_browser": {
            "path": str(browser_path) if browser_path else None,
            "version": browser_version,
            "return_code": browser.poll() if browser else None,
            "stderr_tail": _redact_value(
                list(browser_stderr),
                endpoint=public_wisp_endpoint,
                probe_url=public_probe_url,
            ),
        },
        "runtime_result": _redact_value(
            result, endpoint=public_wisp_endpoint, probe_url=public_probe_url
        ),
    }
    serialized = json.dumps(diagnostic, indent=2, sort_keys=True)
    _assert_redacted_public_text(
        serialized,
        endpoint=public_wisp_endpoint,
        probe_url=public_probe_url,
        description="public HTTPS failure diagnostics",
    )
    temporary_path = diagnostic_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        serialized + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(diagnostic_path)
    return diagnostic_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one operator-configured public HTTPS document through "
            "Chromium's WISP socket transport."
        )
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument(
        "--expected-provenance",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--public-wisp-endpoint",
        required=True,
        help="credential-free external wss:// gateway; never persisted",
    )
    parser.add_argument(
        "--public-probe-url",
        required=True,
        help="one project-controlled https:// DNS-hostname:443 document",
    )
    parser.add_argument(
        "--expected-status",
        required=True,
        type=parse_expected_status,
        help="expected final HTTP response status for the exact probe",
    )
    parser.add_argument(
        "--expected-protocol",
        choices=("h2", "http/1.1"),
        required=True,
        help="expected Chromium HTTP protocol; HTTP/3 remains disabled",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="failure directory (default: OUT_DIR/diagnostics-m5-public-https)",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout", type=parse_timeout, default=120.0)
    args = parser.parse_args()

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / "diagnostics-m5-public-https"
    elif not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    public_wisp_endpoint = args.public_wisp_endpoint
    public_probe_url = args.public_probe_url
    server = None
    server_thread = None
    server_started = False
    browser: subprocess.Popen[str] | None = None
    browser_path: Path | None = None
    browser_version: str | None = None
    browser_stderr: deque[str] = deque(maxlen=300)
    browser_stderr_thread: threading.Thread | None = None
    profile: tempfile.TemporaryDirectory[str] | None = None
    artifact_provenance: dict[str, Any] | None = None
    artifact_snapshots: dict[str, bytes] | None = None
    static_snapshots: dict[str, bytes] | None = None
    result: dict[str, Any] | None = None
    context: dict[str, object] | None = None
    stage = "validate_inputs"

    try:
        public_wisp_endpoint = validate_public_wisp_endpoint(
            public_wisp_endpoint
        )
        public_probe_url = validate_public_probe_url(public_probe_url)
        stage = "load_manifest"
        manifest = load_manifest()
        port_revision = checked_output(["git", "rev-parse", "HEAD"])
        versions = manifest_versions(manifest, port_revision)
        stage = "print_context"
        context = print_context(
            "run_m5_public_https_smoke.py",
            manifest,
            case=M5_PUBLIC_HTTPS_CASE,
            gn_args=manifest.get(
                "m3_content_gn_args", manifest.get("gn_args")
            ),
            module_name=args.module_name,
            host_browser_sandbox=not args.no_sandbox,
            transport="WISP v2.1 over an operator-provisioned external WSS gateway",
            configured_endpoint="<redacted>",
            configured_probe="<redacted>",
        )
        stage = "find_browser"
        browser_path, browser_version = find_browser(args.browser)
        print(
            f"{SENTINEL}:HOST_BROWSER "
            + json.dumps(
                {"browser_version": browser_version},
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )

        token = secrets.token_urlsafe(24)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        stage = "verify_test_artifacts"
        verify_no_private_key_pem_artifacts(out_dir, args.module_name)
        stage = "snapshot_public_artifacts"
        (
            artifact_provenance,
            artifact_snapshots,
            static_snapshots,
        ) = snapshot_public_artifacts(out_dir, args.module_name)
        if args.expected_provenance is not None:
            expected_provenance = parse_expected_public_provenance(
                args.expected_provenance
            )
            validate_public_provenance(
                expected_provenance,
                expected_versions=versions,
                expected_artifacts=artifact_provenance,
            )
        stage = "create_host_server"
        server = create_m3_server(
            "127.0.0.1",
            0,
            out_dir,
            token,
            result_queue,
            module_name=args.module_name,
            artifact_snapshots=artifact_snapshots,
            static_snapshots=static_snapshots,
            require_ahem_font=False,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="chromium-wasm-m5-public-host-server",
            daemon=True,
        )
        server_thread.start()
        server_started = True
        host_url = public_smoke_url(
            server,
            token,
            versions,
            public_wisp_endpoint=public_wisp_endpoint,
            public_probe_url=public_probe_url,
            expected_status=args.expected_status,
            expected_protocol=args.expected_protocol,
            module_name=args.module_name,
            timeout_seconds=min(180.0, max(1.0, args.timeout - 1.0)),
        )

        profile = tempfile.TemporaryDirectory(
            prefix="chromium-wasm-m5-public-"
        )
        stage = "launch_browser"
        browser = subprocess.Popen(
            public_browser_command(
                browser_path, profile.name, host_url, no_sandbox=args.no_sandbox
            ),
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert browser.stderr is not None
        browser_stderr_thread = threading.Thread(
            target=drain_stream,
            args=(browser.stderr, browser_stderr),
            name="chromium-wasm-m5-public-browser-stderr",
            daemon=True,
        )
        browser_stderr_thread.start()
        deadline = time.monotonic() + args.timeout
        stage = "wait_for_result"
        result = wait_for_result(browser, browser_stderr, result_queue, deadline)
        stage = "validate_runtime_contract"
        validate_public_result(
            result,
            expected_versions=versions,
            expected_status=args.expected_status,
            expected_protocol=args.expected_protocol,
            public_wisp_endpoint=public_wisp_endpoint,
            public_probe_url=public_probe_url,
        )
        evidence = public_devtools_network_evidence(
            result,
            expected_status=args.expected_status,
            expected_protocol=args.expected_protocol,
        )
        assert artifact_provenance is not None
        print(
            f"{SENTINEL}:PROVENANCE "
            + json.dumps(
                public_provenance(versions, artifact_provenance),
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(
            f"{SENTINEL}:EVIDENCE "
            + json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        print(f"{SENTINEL}:PASS", flush=True)
        return 0
    except (M0Error, OSError, KeyError, TypeError, ValueError) as exc:
        if browser is not None:
            stop_browser(browser)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)
        try:
            diagnostic_path = write_failure_diagnostics(
                diagnostics_dir,
                stage=stage,
                error=exc,
                context=context,
                browser_path=browser_path,
                browser_version=browser_version,
                browser=browser,
                browser_stderr=browser_stderr,
                result=result,
                public_wisp_endpoint=public_wisp_endpoint,
                public_probe_url=public_probe_url,
            )
            print(
                f"{SENTINEL}:DIAGNOSTICS "
                + json.dumps(
                    {"path": str(diagnostic_path)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
        except (M0Error, OSError, TypeError, ValueError) as diagnostic_error:
            print(
                f"{SENTINEL}:DIAGNOSTICS_FAIL reason={diagnostic_error}",
                file=sys.stderr,
                flush=True,
            )
        print(
            f"{SENTINEL}:FAIL reason="
            + _redact_text(
                str(exc),
                endpoint=public_wisp_endpoint,
                probe_url=public_probe_url,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if browser is not None:
            stop_browser(browser)
        if profile is not None:
            profile.cleanup()
        if server is not None:
            if server_started:
                server.shutdown()
            server.server_close()
        if server_started and server_thread is not None:
            server_thread.join(timeout=3)
        if browser_stderr_thread is not None:
            browser_stderr_thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())

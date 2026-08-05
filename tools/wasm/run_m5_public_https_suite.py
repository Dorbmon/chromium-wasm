#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run an operator-provided public HTTPS M5 suite through fresh WISP lanes.

The one-document public runner owns Chromium/WISP execution and its bounded
DevTools proof. This wrapper deliberately starts that runner in a separate
process for every probe so a browser profile, host page, and WISP connection
cannot carry evidence from one public site into another.

The runtime-only manifest is intentionally external to the checkout. It holds
one credential-free WSS endpoint and two to four direct public HTTPS documents.
Neither the manifest nor its endpoint, hosts, URLs, or child command lines are
written to the aggregate result or failure artifacts.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any
from urllib.parse import quote, quote_plus

from m0_common import M0Error, REPO_ROOT, parse_timeout
from m3_content_server import M5_PUBLIC_HTTPS_CASE
import run_m5_public_https_smoke as public_smoke


SENTINEL = "CHROMIUM_WASM_M5_PUBLIC_HTTPS_SUITE"
MANIFEST_SCHEMA_VERSION = 1
MINIMUM_PUBLIC_PROBES = 2
MAXIMUM_PUBLIC_PROBES = 4
MAXIMUM_MANIFEST_BYTES = 16 * 1024
DEFAULT_MODULE_NAME = public_smoke.DEFAULT_MODULE_NAME
DEFAULT_DIAGNOSTICS_DIRECTORY = "diagnostics-m5-public-https-suite"


@dataclass(frozen=True)
class PublicProbe:
    """One direct, publicly trusted document expectation."""

    public_probe_url: str
    expected_status: int
    expected_protocol: str


@dataclass(frozen=True)
class PublicSuiteConfig:
    """Validated runtime-only configuration for the external public suite."""

    public_wisp_endpoint: str
    probes: tuple[PublicProbe, ...]


@dataclass(frozen=True)
class PublicProbeEvidence:
    """The fixed redacted DevTools/WISP proof for one fresh child process."""

    ordinal: int
    public_devtools_network: dict[str, Any]


class PublicSuiteProbeError(M0Error):
    """A child failed without retaining its runtime-only output in the parent."""

    def __init__(
        self,
        ordinal: int,
        reason: str,
        successful_evidence: tuple[PublicProbeEvidence, ...],
    ) -> None:
        super().__init__(f"public HTTPS suite probe {ordinal} {reason}")
        self.ordinal = ordinal
        self.successful_evidence = successful_evidence


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise M0Error("public HTTPS suite manifest has duplicate object keys")
        result[key] = value
    return result


def _reject_duplicate_evidence_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate public HTTPS evidence key")
        result[key] = value
    return result


def _external_manifest_path(path: Path) -> Path:
    """Resolve a regular operator-owned manifest outside this repository."""

    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, ValueError, UnicodeError) as exc:
        raise M0Error("public HTTPS suite manifest could not be resolved") from exc
    if not resolved.is_file():
        raise M0Error("public HTTPS suite manifest must be a regular file")
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise M0Error("public HTTPS suite manifest must remain outside the repository")


def _load_json_manifest(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as manifest_file:
            serialized_bytes = manifest_file.read(MAXIMUM_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise M0Error("public HTTPS suite manifest could not be read") from exc
    if len(serialized_bytes) > MAXIMUM_MANIFEST_BYTES:
        raise M0Error("public HTTPS suite manifest is too large")
    try:
        serialized = serialized_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise M0Error("public HTTPS suite manifest could not be read") from exc
    try:
        manifest = json.loads(
            serialized, object_pairs_hook=_reject_duplicate_object_keys
        )
    except json.JSONDecodeError as exc:
        raise M0Error("public HTTPS suite manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise M0Error("public HTTPS suite manifest must be a JSON object")
    return manifest


def _validated_manifest_status(value: object) -> int:
    # The public suite consists of direct successful document loads. Error-page
    # behavior belongs to controlled M5 coverage and must not count as a public
    # site success.
    if type(value) is not int or value != 200:
        raise M0Error("public HTTPS suite probe expected_status must be 200")
    return value


def _validated_manifest_protocol(value: object) -> str:
    if not isinstance(value, str) or value not in ("h2", "http/1.1"):
        raise M0Error("public HTTPS suite probe expected_protocol is invalid")
    return value


def load_public_suite_config(manifest_path: Path) -> PublicSuiteConfig:
    """Read and validate all public inputs before a child can start."""

    manifest = _load_json_manifest(_external_manifest_path(manifest_path))
    if set(manifest) != {"schema_version", "public_wisp_endpoint", "probes"}:
        raise M0Error("public HTTPS suite manifest has unsupported fields")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != MANIFEST_SCHEMA_VERSION
    ):
        raise M0Error("public HTTPS suite manifest schema version is invalid")
    public_wisp_endpoint = public_smoke.validate_public_wisp_endpoint(
        manifest["public_wisp_endpoint"]
    )
    raw_probes = manifest["probes"]
    if not isinstance(raw_probes, list) or not (
        MINIMUM_PUBLIC_PROBES <= len(raw_probes) <= MAXIMUM_PUBLIC_PROBES
    ):
        raise M0Error("public HTTPS suite requires two to four probes")

    probes: list[PublicProbe] = []
    seen_urls: set[str] = set()
    seen_hosts: set[str] = set()
    for raw_probe in raw_probes:
        if not isinstance(raw_probe, dict) or set(raw_probe) != {
            "public_probe_url",
            "expected_status",
            "expected_protocol",
        }:
            raise M0Error("public HTTPS suite probe has unsupported fields")
        public_probe_url = public_smoke.validate_public_probe_url(
            raw_probe["public_probe_url"]
        )
        expected_status = _validated_manifest_status(raw_probe["expected_status"])
        expected_protocol = _validated_manifest_protocol(
            raw_probe["expected_protocol"]
        )
        if public_probe_url in seen_urls:
            raise M0Error("public HTTPS suite probes must have distinct URLs")
        hostname = public_smoke._split_public_url(
            public_probe_url, "public HTTPS suite probe"
        ).hostname
        if hostname is None:
            raise M0Error("public HTTPS suite probe hostname is invalid")
        if hostname in seen_hosts:
            raise M0Error("public HTTPS suite probes must have distinct hostnames")
        seen_urls.add(public_probe_url)
        seen_hosts.add(hostname)
        probes.append(
            PublicProbe(
                public_probe_url=public_probe_url,
                expected_status=expected_status,
                expected_protocol=expected_protocol,
            )
        )
    return PublicSuiteConfig(
        public_wisp_endpoint=public_wisp_endpoint,
        probes=tuple(probes),
    )


def public_probe_command(
    config: PublicSuiteConfig,
    probe: PublicProbe,
    ordinal: int,
    *,
    browser: Path | None,
    out_dir: Path,
    module_name: str,
    diagnostics_dir: Path,
    no_sandbox: bool,
    timeout: float,
) -> list[str]:
    """Build, but never log, one independently owned public-runner command."""

    command = [
        sys.executable,
        str(REPO_ROOT / "tools/wasm/run_m5_public_https_smoke.py"),
        "--out-dir",
        str(out_dir),
        "--module-name",
        module_name,
        "--public-wisp-endpoint",
        config.public_wisp_endpoint,
        "--public-probe-url",
        probe.public_probe_url,
        "--expected-status",
        str(probe.expected_status),
        "--expected-protocol",
        probe.expected_protocol,
        "--diagnostics-dir",
        str(diagnostics_dir / f"probe-{ordinal:03d}"),
        "--timeout",
        str(timeout),
    ]
    if browser is not None:
        command.extend(("--browser", str(browser)))
    if no_sandbox:
        command.append("--no-sandbox")
    return command


def _child_devtools_evidence(
    completed: subprocess.CompletedProcess[str], probe: PublicProbe
) -> dict[str, Any] | None:
    """Accept one internally validated, fixed child proof and no contradiction."""

    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    stderr = completed.stderr if isinstance(completed.stderr, str) else ""
    pass_marker = f"{public_smoke.SENTINEL}:PASS"
    fail_prefix = f"{public_smoke.SENTINEL}:FAIL"
    evidence_prefix = f"{public_smoke.SENTINEL}:EVIDENCE "
    stdout_lines = stdout.splitlines()
    stderr_lines = stderr.splitlines()
    stripped_stdout_lines = [line.strip() for line in stdout_lines]
    stripped_stderr_lines = [line.strip() for line in stderr_lines]
    if completed.returncode != 0:
        return None
    if any(
        line.startswith(fail_prefix)
        for line in (*stripped_stdout_lines, *stripped_stderr_lines)
    ):
        return None
    if (
        sum(line == pass_marker for line in stripped_stdout_lines) != 1
        or any(line == pass_marker for line in stripped_stderr_lines)
        or any(line.startswith(evidence_prefix) for line in stripped_stderr_lines)
    ):
        return None
    evidence_indices = [
        index
        for index, line in enumerate(stripped_stdout_lines)
        if line.startswith(evidence_prefix)
    ]
    pass_index = next(
        index
        for index, line in enumerate(stripped_stdout_lines)
        if line == pass_marker
    )
    if (
        len(evidence_indices) != 1
        or not stdout_lines[evidence_indices[0]].startswith(evidence_prefix)
        or evidence_indices[0] >= pass_index
    ):
        return None
    try:
        evidence = json.loads(
            stdout_lines[evidence_indices[0]][len(evidence_prefix) :],
            object_pairs_hook=_reject_duplicate_evidence_keys,
        )
        return public_smoke.validate_public_devtools_network_evidence(
            evidence,
            expected_status=probe.expected_status,
            expected_protocol=probe.expected_protocol,
        )
    except (json.JSONDecodeError, M0Error, ValueError):
        return None


def run_public_suite(
    config: PublicSuiteConfig,
    *,
    browser: Path | None,
    out_dir: Path,
    module_name: str,
    diagnostics_dir: Path,
    no_sandbox: bool,
    timeout: float,
) -> tuple[PublicProbeEvidence, ...]:
    """Run each probe serially in a fresh public-runner process.

    The child owns its timeout and teardown. Do not add a wrapper timeout here:
    terminating its Python process would risk orphaning the separately spawned
    browser process before the child can perform its normal cleanup.
    """

    successful_evidence: list[PublicProbeEvidence] = []
    for ordinal, probe in enumerate(config.probes, start=1):
        command = public_probe_command(
            config,
            probe,
            ordinal,
            browser=browser,
            out_dir=out_dir,
            module_name=module_name,
            diagnostics_dir=diagnostics_dir,
            no_sandbox=no_sandbox,
            timeout=timeout,
        )
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                shell=False,
                text=True,
            )
        except (OSError, ValueError, UnicodeError) as exc:
            raise PublicSuiteProbeError(
                ordinal, "could not start", tuple(successful_evidence)
            ) from exc
        evidence = _child_devtools_evidence(completed, probe)
        if evidence is None:
            raise PublicSuiteProbeError(
                ordinal, "did not pass", tuple(successful_evidence)
            )
        successful_evidence.append(
            PublicProbeEvidence(
                ordinal=ordinal,
                public_devtools_network=evidence,
            )
        )
    return tuple(successful_evidence)


def _assert_redacted_artifact(
    artifact: dict[str, object], config: PublicSuiteConfig
) -> None:
    """Defend the wrapper's no-runtime-input persistence boundary."""

    serialized = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    inputs = [config.public_wisp_endpoint] + [
        probe.public_probe_url for probe in config.probes
    ]
    for value in inputs:
        for rendered in (
            value,
            quote(value, safe=""),
            quote_plus(value),
        ):
            if rendered and rendered in serialized:
                raise M0Error("public HTTPS suite artifact leaked a configured URL")
    if public_smoke.URL_LIKE_VALUE_PATTERN.search(serialized):
        raise M0Error("public HTTPS suite artifact contains an unredacted URL")


def _write_artifact(path: Path, artifact: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_path.replace(path)
    return path


def _result_artifact_path(diagnostics_dir: Path) -> Path:
    return diagnostics_dir / "m5-public-https-suite-result.json"


def _validate_evidence_prefix(
    evidence: tuple[PublicProbeEvidence, ...],
    config: PublicSuiteConfig,
    *,
    expected_ordinals: tuple[int, ...],
) -> None:
    if not all(isinstance(record, PublicProbeEvidence) for record in evidence):
        raise M0Error("public HTTPS suite evidence records are invalid")
    ordinals = tuple(record.ordinal for record in evidence)
    if (
        any(type(ordinal) is not int for ordinal in ordinals)
        or ordinals != expected_ordinals
    ):
        raise M0Error("public HTTPS suite evidence ordinals are incomplete")
    for record, probe in zip(evidence, config.probes):
        try:
            public_smoke.validate_public_devtools_network_evidence(
                record.public_devtools_network,
                expected_status=probe.expected_status,
                expected_protocol=probe.expected_protocol,
            )
        except M0Error as exc:
            raise M0Error("public HTTPS suite evidence is invalid") from exc


def _serialize_evidence(
    evidence: tuple[PublicProbeEvidence, ...]
) -> list[dict[str, object]]:
    return [
        {
            "ordinal": record.ordinal,
            "publicDevtoolsNetwork": record.public_devtools_network,
        }
        for record in evidence
    ]


def write_suite_success_artifact(
    diagnostics_dir: Path,
    *,
    evidence: tuple[PublicProbeEvidence, ...],
    config: PublicSuiteConfig,
) -> Path:
    _validate_evidence_prefix(
        evidence,
        config,
        expected_ordinals=tuple(range(1, len(config.probes) + 1)),
    )
    artifact: dict[str, object] = {
        "schema_version": 1,
        "runner": "run_m5_public_https_suite.py",
        "case": M5_PUBLIC_HTTPS_CASE,
        "status": "pass",
        "probe_count": len(config.probes),
        "probes": _serialize_evidence(evidence),
    }
    _assert_redacted_artifact(artifact, config)
    return _write_artifact(_result_artifact_path(diagnostics_dir), artifact)


def write_suite_failure_artifact(
    diagnostics_dir: Path,
    *,
    error: PublicSuiteProbeError,
    config: PublicSuiteConfig,
) -> Path:
    if type(error.ordinal) is not int or not 1 <= error.ordinal <= len(config.probes):
        raise M0Error("public HTTPS suite failed probe ordinal is invalid")
    _validate_evidence_prefix(
        error.successful_evidence,
        config,
        expected_ordinals=tuple(range(1, error.ordinal)),
    )
    artifact: dict[str, object] = {
        "schema_version": 1,
        "runner": "run_m5_public_https_suite.py",
        "case": M5_PUBLIC_HTTPS_CASE,
        "status": "fail",
        "probe_count": len(config.probes),
        "completedProbes": _serialize_evidence(error.successful_evidence),
        "failedProbeOrdinal": error.ordinal,
        "failure": "child_public_runner_did_not_pass",
    }
    _assert_redacted_artifact(artifact, config)
    return _write_artifact(_result_artifact_path(diagnostics_dir), artifact)


def write_preflight_failure_artifact(
    diagnostics_dir: Path, *, failure: str
) -> Path:
    """Replace this fresh run's result with a safe failure before config exists."""

    artifact: dict[str, object] = {
        "schema_version": 1,
        "runner": "run_m5_public_https_suite.py",
        "case": M5_PUBLIC_HTTPS_CASE,
        "status": "fail",
        "failure": failure,
    }
    if public_smoke.URL_LIKE_VALUE_PATTERN.search(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    ):
        raise M0Error("public HTTPS suite preflight artifact contains a URL")
    return _write_artifact(_result_artifact_path(diagnostics_dir), artifact)


def create_run_diagnostics_directory(diagnostics_dir: Path) -> Path:
    """Give every invocation a fresh opaque evidence directory."""

    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(16):
        run_directory = diagnostics_dir / f"run-{secrets.token_hex(12)}"
        try:
            run_directory.mkdir()
        except FileExistsError:
            continue
        return run_directory
    raise M0Error("could not allocate a fresh public HTTPS suite run directory")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run two to four operator-configured public HTTPS documents through "
            "fresh Chromium WISP lifecycles."
        )
    )
    parser.add_argument(
        "--suite-manifest",
        required=True,
        type=Path,
        help="external JSON manifest; it must remain outside this checkout",
    )
    parser.add_argument("--browser", type=Path)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("out/wasm-content-m3")
    )
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME)
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        help="redacted artifact directory (default: OUT_DIR public-suite diagnostics)",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="disable the host browser sandbox (isolated CI only)",
    )
    parser.add_argument("--timeout-per-probe", type=parse_timeout, default=120.0)
    args = parser.parse_args()

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    diagnostics_dir = args.diagnostics_dir
    if diagnostics_dir is None:
        diagnostics_dir = out_dir / DEFAULT_DIAGNOSTICS_DIRECTORY
    elif not diagnostics_dir.is_absolute():
        diagnostics_dir = REPO_ROOT / diagnostics_dir

    try:
        run_diagnostics_dir = create_run_diagnostics_directory(diagnostics_dir)
    except (M0Error, OSError, ValueError, UnicodeError):
        print(f"{SENTINEL}:FAIL", file=sys.stderr, flush=True)
        return 1
    try:
        config = load_public_suite_config(args.suite_manifest)
    except (M0Error, ValueError, UnicodeError) as exc:
        try:
            write_preflight_failure_artifact(
                run_diagnostics_dir, failure="invalid_manifest"
            )
        except (M0Error, OSError, ValueError, UnicodeError):
            pass
        print(
            f"{SENTINEL}:FAIL run={run_diagnostics_dir.name} reason={exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1

    try:
        # The public children are invoked below by run_public_suite. This safe
        # progress marker contains no runtime-only configuration values.
        print(
            f"{SENTINEL}:START run={run_diagnostics_dir.name} "
            f"probes={len(config.probes)}",
            flush=True,
        )
        evidence = run_public_suite(
            config,
            browser=args.browser,
            out_dir=out_dir,
            module_name=args.module_name,
            diagnostics_dir=run_diagnostics_dir,
            no_sandbox=args.no_sandbox,
            timeout=args.timeout_per_probe,
        )
        write_suite_success_artifact(
            run_diagnostics_dir,
            evidence=evidence,
            config=config,
        )
        # Once the atomic pass artifact exists it is authoritative. A closed
        # report pipe cannot turn that completed run into a contradictory
        # process failure while leaving the result on disk as a pass.
        try:
            for record in evidence:
                print(
                    f"{SENTINEL}:PROBE ordinal={record.ordinal} status=pass",
                    flush=True,
                )
            print(
                f"{SENTINEL}:PASS run={run_diagnostics_dir.name} "
                f"probes={len(evidence)}",
                flush=True,
            )
        except (OSError, ValueError):
            pass
        return 0
    except PublicSuiteProbeError as exc:
        try:
            write_suite_failure_artifact(
                run_diagnostics_dir,
                error=exc,
                config=config,
            )
        except (M0Error, OSError, ValueError, UnicodeError):
            pass
        print(
            f"{SENTINEL}:FAIL run={run_diagnostics_dir.name} probe={exc.ordinal}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    except (M0Error, OSError, ValueError, UnicodeError):
        # Artifact persistence has no runtime-only inputs, but a failure to
        # persist it still cannot be reported as a passed public suite.
        try:
            write_preflight_failure_artifact(
                run_diagnostics_dir, failure="runner_infrastructure_failure"
            )
        except (M0Error, OSError, ValueError, UnicodeError):
            pass
        print(
            f"{SENTINEL}:FAIL run={run_diagnostics_dir.name}",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

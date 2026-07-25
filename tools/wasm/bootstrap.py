#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

from m0_common import (
    M0Error,
    REPO_ROOT,
    TEST262_CHECKOUT_PATH,
    TEST262_DEPS_PATH,
    TEST262_LICENSE_PATH,
    TEST262_REMOTE,
    checked_output,
    fail,
    gn_args_text,
    load_manifest,
    print_context,
    relative_to_repo,
    run,
    validate_test262_manifest,
)


M0_REQUIRED_SUBMODULES = (
    "v8",
    "skia",
    "dawn",
    "angle",
    "boringssl",
    "icu",
    "webrtc",
    "ffmpeg",
    "libyuv",
    "compiler_rt",
    "depot_tools",
    "perfetto",
    "protobuf_javascript",
    "googletest",
)

M3_ADDITIONAL_SUBMODULES = (
    "catapult",
    "ced",
    "crc32c",
    "dragonbox",
    "emoji_segmenter",
    "expat",
    "fast_float",
    "flac",
    "flatbuffers",
    "fp16",
    "freetype",
    "harfbuzz",
    "highway",
    "leveldb",
    "libaddressinput",
    "libcxx",
    "libcxxabi",
    "libgav1",
    "libjpeg_turbo",
    "libphonenumber",
    "libsrtp",
    "libwebm",
    "libwebp",
    "lss",
    "llvm_libc",
    "material_color_utilities",
    "ots",
    "quiche",
    "re2",
    "search_engines_data",
    "snappy",
    "sqlite",
    "vulkan_headers",
    "wuffs",
    "zstd",
)

M3_REQUIRED_SUBMODULES = (
    *M0_REQUIRED_SUBMODULES,
    *M3_ADDITIONAL_SUBMODULES,
)

M3_REQUIRED_NESTED_SUBMODULES = ("dawn_webgpu_headers",)

# Retain the complete current set as the public contract used by source-pin
# tests. Callers selecting a historical milestone should pass its exact set.
REQUIRED_SUBMODULES = M3_REQUIRED_SUBMODULES


def require_equal(label: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise M0Error(f"{label} mismatch: expected {expected}, got {actual}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gitlink_revision(base_revision: str, path: str) -> str:
    entry = checked_output(["git", "ls-tree", base_revision, "--", path])
    fields = entry.split()
    if len(fields) < 3 or fields[1] != "commit":
        raise M0Error(f"{path} is not a gitlink at the Chromium base revision")
    return fields[2]


def nested_gitlink_revision(
    repository: Path, base_revision: str, path: str
) -> str:
    entry = checked_output(
        ["git", "ls-tree", base_revision, "--", path], cwd=repository
    )
    fields = entry.split()
    if len(fields) < 3 or fields[1] != "commit":
        raise M0Error(
            f"{path} is not a gitlink at nested revision {base_revision}"
        )
    return fields[2]


def ensure_source_dependencies(
    manifest: dict[str, object],
    *,
    install: bool,
    required_submodules: tuple[str, ...] | None = None,
) -> None:
    if required_submodules is None:
        required_submodules = REQUIRED_SUBMODULES

    chromium = manifest["chromium"]
    assert isinstance(chromium, dict)
    base_revision = str(chromium["revision"])
    if platform.system() != "Linux" or platform.machine() not in (
        "x86_64",
        "AMD64",
    ):
        raise M0Error("M0 bootstrap currently requires Linux x86_64")
    run(["git", "cat-file", "-e", f"{base_revision}^{{commit}}"])
    run(["git", "merge-base", "--is-ancestor", base_revision, "HEAD"])
    version_lines = checked_output(
        ["git", "show", f"{base_revision}:chrome/VERSION"]
    ).splitlines()
    version_parts = dict(line.split("=", 1) for line in version_lines)
    source_version = ".".join(
        version_parts[key] for key in ("MAJOR", "MINOR", "BUILD", "PATCH")
    )
    require_equal("Chromium version", source_version, str(chromium["tag"]))
    if "commit_timestamp" in chromium:
        require_equal(
            "Chromium commit timestamp",
            checked_output(
                ["git", "show", "-s", "--format=%ct", base_revision]
            ),
            str(chromium["commit_timestamp"]),
        )
    if "commit_position" in chromium:
        commit_message = checked_output(
            ["git", "show", "-s", "--format=%B", base_revision]
        )
        expected_position = (
            f"Cr-Commit-Position: {chromium['commit_position']}"
        )
        if expected_position not in commit_message.splitlines():
            raise M0Error(
                "Chromium commit position mismatch: expected "
                f"{chromium['commit_position']}"
            )

    dependencies = manifest["git_dependencies"]
    assert isinstance(dependencies, dict)
    for name, raw_dependency in dependencies.items():
        assert isinstance(raw_dependency, dict)
        upstream_revision = raw_dependency.get(
            "upstream_revision", raw_dependency["revision"]
        )
        require_equal(
            f"{name} upstream gitlink",
            gitlink_revision(base_revision, str(raw_dependency["path"])),
            str(upstream_revision),
        )
        require_equal(
            f"{name} HEAD gitlink",
            gitlink_revision("HEAD", str(raw_dependency["path"])),
            str(raw_dependency["revision"]),
        )

    def dependency_path(name: str) -> Path:
        dependency = dependencies[name]
        assert isinstance(dependency, dict)
        return REPO_ROOT / str(dependency["path"])

    missing_dependencies = [
        name
        for name in required_submodules
        if not (dependency_path(name) / ".git").exists()
    ]

    if install and missing_dependencies:
        paths = [
            relative_to_repo(dependency_path(name))
            for name in missing_dependencies
        ]
        run(
            [
                "git",
                "submodule",
                "update",
                "--init",
                "--depth=1",
                "--jobs=3",
                "--",
                *paths,
            ],
            capture_output=False,
        )

        missing_dependencies = [
            name
            for name in required_submodules
            if not (dependency_path(name) / ".git").exists()
        ]
    if missing_dependencies:
        raise M0Error(
            "required dependencies are not initialized: "
            + ", ".join(missing_dependencies)
        )

    for name in required_submodules:
        dependency = dependencies[name]
        assert isinstance(dependency, dict)
        dependency_path = REPO_ROOT / str(dependency["path"])
        require_equal(
            f"{name} checkout",
            checked_output(["git", "rev-parse", "HEAD"], cwd=dependency_path),
            str(dependency["revision"]),
        )
        status = checked_output(
            ["git", "status", "--short", "--untracked-files=no"],
            cwd=dependency_path,
        )
        require_equal(f"{name} worktree", status, "")


def ensure_nested_source_dependencies(
    manifest: dict[str, object],
    *,
    install: bool,
    required_submodules: tuple[str, ...] = M3_REQUIRED_NESTED_SUBMODULES,
) -> None:
    dependencies = manifest["git_dependencies"]
    nested_dependencies = manifest["nested_git_dependencies"]
    assert isinstance(dependencies, dict)
    assert isinstance(nested_dependencies, dict)

    for name in required_submodules:
        nested = nested_dependencies[name]
        assert isinstance(nested, dict)
        parent_name = str(nested["parent"])
        parent = dependencies[parent_name]
        assert isinstance(parent, dict)
        parent_root = REPO_ROOT / str(parent["path"])
        relative_path = Path(str(nested["path"]))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise M0Error(
                f"nested dependency path must stay in {parent_name}: "
                f"{relative_path}"
            )
        nested_root = parent_root / relative_path
        require_equal(
            f"{name} parent gitlink",
            nested_gitlink_revision(
                parent_root,
                str(parent["revision"]),
                relative_path.as_posix(),
            ),
            str(nested["revision"]),
        )

        if install and not (nested_root / ".git").exists():
            run(
                [
                    "git",
                    "submodule",
                    "update",
                    "--init",
                    "--depth=1",
                    "--jobs=3",
                    "--",
                    relative_path.as_posix(),
                ],
                cwd=parent_root,
                capture_output=False,
            )
        if not (nested_root / ".git").exists():
            raise M0Error(
                f"required nested dependency is not initialized: {name}"
            )
        require_equal(
            f"{name} checkout",
            checked_output(["git", "rev-parse", "HEAD"], cwd=nested_root),
            str(nested["revision"]),
        )
        require_equal(
            f"{name} worktree",
            checked_output(
                ["git", "status", "--short", "--untracked-files=no"],
                cwd=nested_root,
            ),
            "",
        )


def test262_checkout_path(test262: dict[str, object]) -> Path:
    configured_path = Path(str(test262["path"]))
    if configured_path != TEST262_CHECKOUT_PATH:
        raise M0Error(
            "Test262 checkout path mismatch: "
            f"expected {TEST262_CHECKOUT_PATH}, got {configured_path}"
        )
    return REPO_ROOT / configured_path


def run_test262_git(
    checkout_root: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", *arguments],
        cwd=checkout_root,
        check=check,
        env={"GIT_OPTIONAL_LOCKS": "0"},
    )


def test262_git_output(checkout_root: Path, *arguments: str) -> str:
    return run_test262_git(checkout_root, *arguments).stdout.strip()


def verify_test262_v8_deps_pin(manifest: dict[str, object]) -> None:
    test262 = validate_test262_manifest(manifest)
    dependencies = manifest["git_dependencies"]
    assert isinstance(dependencies, dict)
    v8 = dependencies["v8"]
    assert isinstance(v8, dict)
    v8_root = REPO_ROOT / str(v8["path"])
    deps_text = checked_output(
        ["git", "show", f"{v8['revision']}:DEPS"],
        cwd=v8_root,
    )

    chromium_url = "https://chromium.googlesource.com"
    chromium_url_declaration = f"  'chromium_url': '{chromium_url}',"
    dependency_key = f"  '{TEST262_DEPS_PATH}':"
    remote_suffix = TEST262_REMOTE.removeprefix(chromium_url)
    expected_entry = (
        f"{dependency_key}\n"
        "    Var('chromium_url') + "
        f"'{remote_suffix}' + '@' + '{test262['revision']}',"
    )
    if deps_text.count("'chromium_url':") != 1:
        raise M0Error(
            "V8 DEPS must define chromium_url exactly once"
        )
    if chromium_url_declaration not in deps_text:
        raise M0Error("V8 DEPS chromium_url mismatch")
    if deps_text.count(dependency_key) != 1:
        raise M0Error(
            "V8 DEPS must define the Test262 dependency exactly once"
        )
    if expected_entry not in deps_text:
        raise M0Error("V8 DEPS Test262 pin mismatch")


def verify_test262_checkout(
    test262: dict[str, object], checkout_root: Path
) -> None:
    if checkout_root.is_symlink():
        raise M0Error("pinned Test262 checkout must not be a symlink")
    git_directory = checkout_root / ".git"
    if (
        not checkout_root.is_dir()
        or not git_directory.is_dir()
        or git_directory.is_symlink()
    ):
        raise M0Error("pinned Test262 checkout is not installed")

    sparse_checkout = run_test262_git(
        checkout_root,
        "config",
        "--bool",
        "--get",
        "core.sparseCheckout",
        check=False,
    )
    if sparse_checkout.returncode not in (0, 1):
        raise M0Error("cannot inspect Test262 sparse-checkout configuration")
    if sparse_checkout.stdout.strip() == "true":
        raise M0Error("pinned Test262 checkout must not be sparse")

    index_records = run_test262_git(
        checkout_root, "ls-files", "-v", "-z"
    ).stdout.split("\0")
    if any(
        record and not record.startswith("H ")
        for record in index_records
    ):
        raise M0Error(
            "pinned Test262 checkout has hidden index flags"
        )

    require_equal(
        "Test262 worktree root",
        str(
            Path(
                test262_git_output(
                    checkout_root, "rev-parse", "--show-toplevel"
                )
            ).resolve()
        ),
        str(checkout_root.resolve()),
    )
    require_equal(
        "Test262 checkout",
        test262_git_output(
            checkout_root, "rev-parse", "HEAD^{commit}"
        ),
        str(test262["revision"]),
    )
    require_equal(
        "Test262 HEAD",
        test262_git_output(
            checkout_root, "rev-parse", "--abbrev-ref", "HEAD"
        ),
        "HEAD",
    )
    require_equal(
        "Test262 origin",
        test262_git_output(
            checkout_root, "remote", "get-url", "--all", "origin"
        ),
        str(test262["remote"]),
    )
    require_equal(
        "Test262 worktree",
        test262_git_output(
            checkout_root,
            "status",
            "--short",
            "--untracked-files=all",
        ),
        "",
    )

    license_path = checkout_root / TEST262_LICENSE_PATH
    if not license_path.is_file() or license_path.is_symlink():
        raise M0Error("pinned Test262 LICENSE is missing")
    require_equal(
        "Test262 LICENSE size",
        str(license_path.stat().st_size),
        str(test262["license_size_bytes"]),
    )
    require_equal(
        "Test262 LICENSE hash",
        sha256(license_path),
        str(test262["license_sha256"]),
    )


def install_test262_checkout(
    test262: dict[str, object], checkout_root: Path
) -> None:
    if os.path.lexists(checkout_root):
        try:
            verify_test262_checkout(test262, checkout_root)
        except M0Error as exc:
            raise M0Error(
                "existing Test262 checkout is invalid; "
                f"refusing to overwrite it: {exc}"
            ) from exc
        return

    try:
        checkout_root.parent.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise M0Error(
            "Test262 checkout parent must stay in the checkout"
        ) from exc
    checkout_root.parent.mkdir(parents=True, exist_ok=True)

    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{checkout_root.name}.install-",
            dir=checkout_root.parent,
        )
    )
    candidate_root = staging_root / "checkout"
    try:
        run(["git", "init", "--quiet", str(candidate_root)])
        run(
            [
                "git",
                "remote",
                "add",
                "origin",
                str(test262["remote"]),
            ],
            cwd=candidate_root,
        )
        run(
            [
                "git",
                "fetch",
                "--depth=1",
                "--no-tags",
                "origin",
                str(test262["revision"]),
            ],
            cwd=candidate_root,
            capture_output=False,
        )
        require_equal(
            "Test262 fetched revision",
            checked_output(
                ["git", "rev-parse", "FETCH_HEAD^{commit}"],
                cwd=candidate_root,
            ),
            str(test262["revision"]),
        )
        run(
            [
                "git",
                "-c",
                "advice.detachedHead=false",
                "checkout",
                "--quiet",
                "--detach",
                "FETCH_HEAD",
            ],
            cwd=candidate_root,
        )
        verify_test262_checkout(test262, candidate_root)
        if os.path.lexists(checkout_root):
            raise M0Error(
                "Test262 checkout path appeared during installation"
            )
        os.replace(candidate_root, checkout_root)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def ensure_test262(
    manifest: dict[str, object], *, install: bool
) -> None:
    test262 = validate_test262_manifest(manifest)
    verify_test262_v8_deps_pin(manifest)
    checkout_root = test262_checkout_path(test262)
    if install:
        install_test262_checkout(test262, checkout_root)
    else:
        verify_test262_checkout(test262, checkout_root)


def ensure_depot_tools_bootstrap(
    manifest: dict[str, object], *, install: bool
) -> tuple[Path, Path]:
    dependencies = manifest["git_dependencies"]
    assert isinstance(dependencies, dict)
    depot_dependency = dependencies["depot_tools"]
    assert isinstance(depot_dependency, dict)
    depot_tools = REPO_ROOT / str(depot_dependency["path"])
    cipd_wrapper = depot_tools / "cipd"
    cipd_client = depot_tools / ".cipd_client"

    bootstrap = manifest["depot_tools_bootstrap"]
    assert isinstance(bootstrap, dict)
    require_equal(
        "depot_tools CIPD client pin",
        (depot_tools / "cipd_client_version").read_text(encoding="utf-8").strip(),
        f"git_revision:{bootstrap['cipd_client_revision']}",
    )
    if install and not cipd_client.is_file():
        run([str(cipd_wrapper), "version"])
    if not cipd_client.is_file():
        raise M0Error("pinned depot_tools CIPD client is not installed")
    require_equal(
        "depot_tools CIPD client hash",
        sha256(cipd_client),
        str(bootstrap["cipd_client_sha256"]),
    )
    cipd_version = run([str(cipd_client), "version"]).stdout
    if str(bootstrap["cipd_client_instance"]) not in cipd_version:
        raise M0Error("depot_tools CIPD client instance mismatch")
    if f"cipd {bootstrap['cipd_client_version']}" not in cipd_version:
        raise M0Error("depot_tools CIPD client version mismatch")

    depot_manifest_lines = (
        depot_tools / "bootstrap/manifest.txt"
    ).read_text(encoding="utf-8").splitlines()
    expected_python_pin = (
        f"{bootstrap['python_cipd_template']} "
        f"{bootstrap['python_cipd_tag']}"
    )
    if expected_python_pin not in depot_manifest_lines:
        raise M0Error("depot_tools manifest Python pin mismatch")

    bootstrap_name = f"bootstrap-{bootstrap['python_bootstrap_version']}_bin"
    bootstrap_root = depot_tools / bootstrap_name
    python_executable = bootstrap_root / "python3/bin/python3"
    if install:
        run(
            [
                str(cipd_client),
                "ensure",
                "-root",
                str(bootstrap_root),
                "-ensure-file",
                str(Path(__file__).with_name("depot_tools_python.ensure")),
            ],
            capture_output=False,
        )
        run(
            [
                str(python_executable),
                "bootstrap/bootstrap.py",
                "--bootstrap-name",
                bootstrap_name,
            ],
            cwd=depot_tools,
            capture_output=False,
        )

    python_reldir = depot_tools / "python3_bin_reldir.txt"
    if not python_reldir.is_file():
        raise M0Error("depot_tools Python path has not been generated")
    require_equal(
        "depot_tools Python path",
        python_reldir.read_text(encoding="utf-8").strip(),
        f"{bootstrap_name}/python3/bin",
    )
    if not python_executable.is_file():
        raise M0Error("pinned depot_tools Python is not installed")

    version_metadata_path = (
        bootstrap_root / "python3/.versions/cpython3.cipd_version"
    )
    if not version_metadata_path.is_file():
        raise M0Error("depot_tools Python CIPD metadata is missing")
    version_metadata = json.loads(
        version_metadata_path.read_text(encoding="utf-8")
    )
    require_equal(
        "depot_tools Python package",
        str(version_metadata["package_name"]),
        str(bootstrap["python_cipd_package"]),
    )
    require_equal(
        "depot_tools Python instance",
        str(version_metadata["instance_id"]),
        str(bootstrap["python_cipd_instance"]),
    )
    python_version = run([str(python_executable), "--version"]).stdout.strip()
    require_equal(
        "depot_tools Python version",
        python_version,
        f"Python {bootstrap['python_runtime_version']}",
    )
    require_equal(
        "depot_tools Python hash",
        sha256(python_executable),
        str(bootstrap["python_sha256"]),
    )
    return cipd_client, python_executable


def verify_toolchain_ensure_pins(manifest: dict[str, object]) -> None:
    ensure_lines = (
        Path(__file__).with_name("toolchain.ensure")
    ).read_text(encoding="utf-8").splitlines()
    for name in ("gn", "ninja", "gperf"):
        tool = manifest[name]
        assert isinstance(tool, dict)
        expected = f"{tool['cipd_package']} {tool['cipd_instance']}"
        if ensure_lines.count(expected) != 1:
            raise M0Error(
                f"toolchain.ensure must contain exactly one {name} pin: "
                f"{expected}"
            )

    gperf = manifest["gperf"]
    assert isinstance(gperf, dict)
    deps_text = (REPO_ROOT / "DEPS").read_text(encoding="utf-8")
    for expected in (
        f"'package': '{gperf['cipd_package'].replace('linux-amd64', '${{platform}}')}'",
        f"'version': '{gperf['cipd_tag']}'",
    ):
        if deps_text.count(expected) != 1:
            raise M0Error(f"Chromium DEPS is missing gperf pin {expected}")


def ensure_build_tools(
    manifest: dict[str, object], cipd: Path, *, install: bool
) -> None:
    verify_toolchain_ensure_pins(manifest)
    if install:
        run(
            [
                str(cipd),
                "ensure",
                "-root",
                str(REPO_ROOT),
                "-ensure-file",
                str(Path(__file__).with_name("toolchain.ensure")),
            ],
            capture_output=False,
        )

    gn = REPO_ROOT / "buildtools/linux64/gn"
    ninja = REPO_ROOT / "third_party/ninja/ninja"
    if not gn.is_file() or not ninja.is_file():
        raise M0Error("pinned GN and Ninja are not installed")

    gn_pin = manifest["gn"]
    ninja_pin = manifest["ninja"]
    assert isinstance(gn_pin, dict) and isinstance(ninja_pin, dict)
    require_equal(
        "GN version",
        checked_output([str(gn), "--version"]),
        str(gn_pin["version_output"]),
    )
    require_equal("GN hash", sha256(gn), str(gn_pin["sha256"]))
    require_equal(
        "Ninja version",
        checked_output([str(ninja), "--version"]),
        str(ninja_pin["version_output"]),
    )
    require_equal("Ninja hash", sha256(ninja), str(ninja_pin["sha256"]))

    gperf_pin = manifest["gperf"]
    assert isinstance(gperf_pin, dict)
    gperf = REPO_ROOT / str(gperf_pin["path"])
    if not gperf.is_file():
        raise M0Error("pinned gperf is not installed")
    version_lines = checked_output([str(gperf), "--version"]).splitlines()
    if not version_lines:
        raise M0Error("pinned gperf returned no version")
    require_equal(
        "gperf version", version_lines[0], str(gperf_pin["version_output"])
    )
    require_equal("gperf hash", sha256(gperf), str(gperf_pin["sha256"]))


def webui_node_modules_paths(
    node_modules: dict[str, object],
) -> tuple[Path, Path]:
    configured_path = Path(str(node_modules["path"]))
    configured_archive = Path(str(node_modules["archive_path"]))
    expected_path = Path("third_party/node/node_modules")
    expected_archive = Path("third_party/node/node_modules.tar.gz")
    if configured_path != expected_path:
        raise M0Error(
            "WebUI node_modules path mismatch: "
            f"expected {expected_path}, got {configured_path}"
        )
    if configured_archive != expected_archive:
        raise M0Error(
            "WebUI node_modules archive path mismatch: "
            f"expected {expected_archive}, got {configured_archive}"
        )
    return REPO_ROOT / configured_path, REPO_ROOT / configured_archive


def chromium_node_runtime_paths(
    node_runtime: dict[str, object],
) -> tuple[Path, Path]:
    configured_path = Path(str(node_runtime["path"]))
    configured_archive = Path(str(node_runtime["archive_path"]))
    configured_archive_root = str(node_runtime["archive_root"])
    expected_path = Path("third_party/node/linux/node-linux-x64")
    expected_archive = Path(
        "third_party/node/linux/node-linux-x64.tar.gz"
    )
    if configured_path != expected_path:
        raise M0Error(
            "Chromium Node runtime path mismatch: "
            f"expected {expected_path}, got {configured_path}"
        )
    if configured_archive != expected_archive:
        raise M0Error(
            "Chromium Node runtime archive path mismatch: "
            f"expected {expected_archive}, got {configured_archive}"
        )
    if configured_archive_root != "node-linux-x64":
        raise M0Error(
            "Chromium Node runtime archive root mismatch: "
            "expected node-linux-x64, got "
            f"{configured_archive_root}"
        )
    return REPO_ROOT / configured_path, REPO_ROOT / configured_archive


def verify_gcs_archive_deps_pin(
    artifact: dict[str, object], *, deps_path: str, label: str
) -> None:
    deps_text = (REPO_ROOT / "DEPS").read_text(encoding="utf-8")
    marker = f"'{deps_path}': {{"
    deps_lines = deps_text.splitlines()
    marker_lines = [
        index
        for index, line in enumerate(deps_lines)
        if line.strip() == marker
    ]
    if len(marker_lines) != 1:
        raise M0Error(
            f"Chromium DEPS must contain exactly one {label} entry: "
            f"{deps_path}"
        )
    start = marker_lines[0]
    entry_indent = len(deps_lines[start]) - len(deps_lines[start].lstrip())
    end = len(deps_lines)
    for index in range(start + 1, len(deps_lines)):
        line = deps_lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if (
            indent == entry_indent
            and stripped.startswith("'src/")
            and stripped.endswith((": {", ":"))
        ):
            end = index
            break
    entry_text = "\n".join(deps_lines[start:end])
    for expected in (
        f"'bucket': '{artifact['bucket']}'",
        f"'object_name': '{artifact['object_name']}'",
        f"'sha256sum': '{artifact['sha256']}'",
        f"'size_bytes': {artifact['size_bytes']},",
        f"'generation': {artifact['generation']},",
        f"'output_file': '{artifact['output_file']}'",
    ):
        if entry_text.count(expected) != 1:
            raise M0Error(
                f"Chromium DEPS is missing {label} pin {expected}"
            )


def verify_webui_node_modules_deps_pin(
    node_modules: dict[str, object],
) -> None:
    verify_gcs_archive_deps_pin(
        node_modules,
        deps_path="src/third_party/node/node_modules",
        label="WebUI node_modules",
    )
    sha1_path = REPO_ROOT / str(node_modules["sha1_path"])
    if sha1_path.is_symlink() or not sha1_path.is_file():
        raise M0Error("WebUI node_modules SHA-1 pin is missing")
    require_equal(
        "WebUI node_modules SHA-1 pin",
        sha1_path.read_text(encoding="utf-8").strip(),
        str(node_modules["object_name"]),
    )


def verify_chromium_node_runtime_deps_pin(
    node_runtime: dict[str, object],
) -> None:
    verify_gcs_archive_deps_pin(
        node_runtime,
        deps_path="src/third_party/node/linux",
        label="Chromium Node runtime",
    )


def _archive_member_path(name: str, *, label: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise M0Error(f"unsafe {label} archive path: {name}")
    return "/".join(part for part in path.parts if part not in ("", "."))


def _validate_archive_symlink(
    name: str,
    linkname: str,
    *,
    label: str,
    archive_prefix: str = "",
) -> None:
    target = PurePosixPath(linkname)
    if target.is_absolute():
        raise M0Error(
            f"unsafe {label} archive symlink target: {name} -> {linkname}"
        )
    resolved_parts = list(PurePosixPath(name).parent.parts)
    for part in target.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved_parts:
                raise M0Error(
                    f"unsafe {label} archive symlink target: "
                    f"{name} -> {linkname}"
                )
            resolved_parts.pop()
        else:
            resolved_parts.append(part)
    if archive_prefix:
        prefix_parts = list(PurePosixPath(archive_prefix).parts)
        if resolved_parts[: len(prefix_parts)] != prefix_parts:
            raise M0Error(
                f"unsafe {label} archive symlink target: "
                f"{name} -> {linkname}"
            )


def _hash_stream(input_file: object) -> str:
    digest = hashlib.sha256()
    read = getattr(input_file, "read")
    for chunk in iter(lambda: read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _archive_tree(
    archive_path: Path, *, label: str, archive_prefix: str = ""
) -> dict[str, tuple[str, int, int, str]]:
    entries: dict[str, tuple[str, int, int, str]] = {}
    normalized_prefix = (
        _archive_member_path(archive_prefix, label=label)
        if archive_prefix
        else ""
    )
    prefix_with_separator = (
        f"{normalized_prefix}/" if normalized_prefix else ""
    )
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                name = _archive_member_path(member.name, label=label)
                if not name:
                    continue
                if normalized_prefix:
                    if name == normalized_prefix:
                        if not member.isdir():
                            raise M0Error(
                                f"{label} archive root is not a directory: "
                                f"{name}"
                            )
                        continue
                    if not name.startswith(prefix_with_separator):
                        raise M0Error(
                            f"{label} archive path is outside "
                            f"{normalized_prefix}: {name}"
                        )
                    name = name[len(prefix_with_separator) :]
                if name in entries:
                    raise M0Error(
                        f"duplicate {label} archive path: {name}"
                    )
                mode = member.mode & 0o777
                if member.isdir():
                    entries[name] = ("directory", 0, 0, "")
                elif member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise M0Error(
                            f"failed to read {label} archive member: {name}"
                        )
                    entries[name] = (
                        "file",
                        mode,
                        member.size,
                        _hash_stream(extracted),
                    )
                elif member.issym():
                    _validate_archive_symlink(
                        member.name,
                        member.linkname,
                        label=label,
                        archive_prefix=normalized_prefix,
                    )
                    entries[name] = (
                        "symlink",
                        0,
                        0,
                        member.linkname,
                    )
                else:
                    raise M0Error(
                        f"unsupported {label} archive member: {name}"
                    )
    except (OSError, KeyError, tarfile.TarError) as exc:
        raise M0Error(
            f"failed to inspect pinned {label} archive: {exc}"
        ) from exc
    if not entries:
        raise M0Error(f"pinned {label} archive has no content")
    return entries


def _installed_tree(
    installed_root: Path, *, label: str
) -> dict[str, tuple[str, int, int, str]]:
    entries: dict[str, tuple[str, int, int, str]] = {}
    try:
        for path in installed_root.rglob("*"):
            name = path.relative_to(installed_root).as_posix()
            metadata = path.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if path.is_symlink():
                entries[name] = ("symlink", 0, 0, os.readlink(path))
            elif path.is_dir():
                entries[name] = ("directory", 0, 0, "")
            elif path.is_file():
                entries[name] = (
                    "file",
                    mode,
                    metadata.st_size,
                    sha256(path),
                )
            else:
                raise M0Error(
                    f"unsupported installed {label} path: {name}"
                )
    except OSError as exc:
        raise M0Error(
            f"failed to inspect installed {label}: {exc}"
        ) from exc
    return entries


def verify_gcs_archive(
    artifact: dict[str, object], archive_path: Path, *, label: str
) -> None:
    if archive_path.is_symlink() or not archive_path.is_file():
        raise M0Error(f"pinned {label} archive is not installed")
    require_equal(
        f"{label} archive size",
        str(archive_path.stat().st_size),
        str(artifact["size_bytes"]),
    )
    require_equal(
        f"{label} archive SHA-256",
        sha256(archive_path),
        str(artifact["sha256"]),
    )
    require_equal(
        f"{label} archive SHA-1",
        sha1(archive_path),
        str(artifact["object_name"]),
    )


def verify_archive_tree(
    archive_path: Path,
    installed_root: Path,
    *,
    label: str,
    archive_prefix: str = "",
) -> None:
    if installed_root.is_symlink() or not installed_root.is_dir():
        raise M0Error(f"pinned {label} tree is not installed")
    expected = _archive_tree(
        archive_path, label=label, archive_prefix=archive_prefix
    )
    actual = _installed_tree(installed_root, label=label)
    missing = sorted(expected.keys() - actual.keys())
    if missing:
        raise M0Error(f"installed {label} is missing {missing[0]}")
    unexpected = sorted(actual.keys() - expected.keys())
    if unexpected:
        raise M0Error(f"installed {label} has unexpected {unexpected[0]}")
    for name in sorted(expected):
        if actual[name] != expected[name]:
            raise M0Error(f"installed {label} entry mismatch: {name}")


def download_gcs_archive(
    artifact: dict[str, object], archive_path: Path, *, label: str
) -> None:
    url = (
        "https://storage.googleapis.com/"
        f"{artifact['bucket']}/{artifact['object_name']}"
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "chromium-wasm-bootstrap/1"}
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            archive_path.open("xb") as output_file,
        ):
            copied = 0
            expected_size = int(artifact["size_bytes"])
            while chunk := response.read(1024 * 1024):
                copied += len(chunk)
                if copied > expected_size:
                    raise M0Error(
                        f"pinned {label} archive exceeds "
                        f"{expected_size} bytes"
                    )
                output_file.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        raise M0Error(
            f"failed to download pinned {label} archive: {exc}"
        ) from exc
    verify_gcs_archive(artifact, archive_path, label=label)


def install_gcs_archive_tree(
    artifact: dict[str, object],
    installed_root: Path,
    archive_path: Path,
    *,
    label: str,
    archive_prefix: str = "",
    staging_prefix: str,
) -> None:
    installed_root.parent.mkdir(parents=True, exist_ok=True)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if not os.path.lexists(archive_path):
        archive_staging = Path(
            tempfile.mkdtemp(
                prefix=f".{staging_prefix}.archive-",
                dir=archive_path.parent,
            )
        )
        candidate_archive = archive_staging / archive_path.name
        try:
            download_gcs_archive(
                artifact, candidate_archive, label=label
            )
            if os.path.lexists(archive_path):
                raise M0Error(
                    f"{label} archive path appeared during installation"
                )
            os.replace(candidate_archive, archive_path)
        finally:
            shutil.rmtree(archive_staging, ignore_errors=True)
    verify_gcs_archive(artifact, archive_path, label=label)

    if os.path.lexists(installed_root):
        verify_archive_tree(
            archive_path,
            installed_root,
            label=label,
            archive_prefix=archive_prefix,
        )
        return

    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{staging_prefix}.install-",
            dir=installed_root.parent,
        )
    )
    extract_root = staging_root / "contents"
    extract_root.mkdir()
    try:
        _archive_tree(
            archive_path, label=label, archive_prefix=archive_prefix
        )
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                archive.extractall(extract_root, filter="data")
        except (OSError, tarfile.TarError) as exc:
            raise M0Error(
                f"failed to extract pinned {label} archive: {exc}"
            ) from exc
        candidate_root = (
            extract_root / archive_prefix if archive_prefix else extract_root
        )
        verify_archive_tree(
            archive_path,
            candidate_root,
            label=label,
            archive_prefix=archive_prefix,
        )
        if os.path.lexists(installed_root):
            raise M0Error(
                f"{label} path appeared during installation"
            )
        os.replace(candidate_root, installed_root)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def ensure_webui_node_modules(
    manifest: dict[str, object], *, install: bool
) -> None:
    node_modules = manifest["webui_node_modules"]
    assert isinstance(node_modules, dict)
    verify_webui_node_modules_deps_pin(node_modules)
    node_modules_root, archive_path = webui_node_modules_paths(node_modules)
    if install:
        install_gcs_archive_tree(
            node_modules,
            node_modules_root,
            archive_path,
            label="WebUI node_modules",
            staging_prefix="node_modules",
        )
    else:
        verify_gcs_archive(
            node_modules, archive_path, label="WebUI node_modules"
        )
        verify_archive_tree(
            archive_path,
            node_modules_root,
            label="WebUI node_modules",
        )


def verify_chromium_node_runtime(
    node_runtime: dict[str, object],
    runtime_root: Path,
    archive_path: Path,
) -> None:
    label = "Chromium Node runtime"
    verify_gcs_archive(node_runtime, archive_path, label=label)
    verify_archive_tree(
        archive_path,
        runtime_root,
        label=label,
        archive_prefix=str(node_runtime["archive_root"]),
    )
    executable_path = Path(str(node_runtime["executable_path"]))
    if executable_path != Path("bin/node"):
        raise M0Error(
            "Chromium Node executable path mismatch: "
            f"expected bin/node, got {executable_path}"
        )
    executable = runtime_root / executable_path
    if executable.is_symlink() or not executable.is_file():
        raise M0Error("pinned Chromium Node executable is not installed")
    require_equal(
        "Chromium Node executable hash",
        sha256(executable),
        str(node_runtime["executable_sha256"]),
    )
    require_equal(
        "Chromium Node version",
        checked_output([str(executable), "--version"]),
        str(node_runtime["version_output"]),
    )


def ensure_chromium_node_runtime(
    manifest: dict[str, object], *, install: bool
) -> None:
    node_runtime = manifest["chromium_node_runtime"]
    assert isinstance(node_runtime, dict)
    verify_chromium_node_runtime_deps_pin(node_runtime)
    runtime_root, archive_path = chromium_node_runtime_paths(node_runtime)
    if install:
        install_gcs_archive_tree(
            node_runtime,
            runtime_root,
            archive_path,
            label="Chromium Node runtime",
            archive_prefix=str(node_runtime["archive_root"]),
            staging_prefix="node_runtime",
        )
    verify_chromium_node_runtime(
        node_runtime, runtime_root, archive_path
    )


def ensure_host_clang(
    manifest: dict[str, object],
    bootstrap_python: Path,
    *,
    install: bool,
) -> None:
    clang_pin = manifest["host_clang"]
    assert isinstance(clang_pin, dict)
    clang_root = REPO_ROOT / str(clang_pin["path"])
    update_script = REPO_ROOT / "tools/clang/scripts/update.py"

    if install:
        run(
            [
                str(bootstrap_python),
                str(update_script),
                "--output-dir",
                str(clang_root),
            ],
            capture_output=False,
        )

    clang = clang_root / "bin/clang"
    stamp = clang_root / "cr_build_revision"
    if not clang.is_file() or not stamp.is_file():
        raise M0Error("pinned Chromium host Clang is not installed")

    require_equal(
        "Chromium host Clang revision",
        checked_output(
            [
                str(bootstrap_python),
                str(update_script),
                "--output-dir",
                str(clang_root),
                "--print-revision",
            ]
        ),
        str(clang_pin["revision"]),
    )
    require_equal(
        "Chromium host Clang stamp",
        stamp.read_text(encoding="utf-8").strip().partition(",")[0],
        str(clang_pin["revision"]),
    )
    deps_text = (REPO_ROOT / "DEPS").read_text(encoding="utf-8")
    if str(clang_pin["archive_sha256"]) not in deps_text:
        raise M0Error("Chromium DEPS is missing the host Clang archive pin")
    clang_version = run([str(clang), "--version"]).stdout.splitlines()
    if not clang_version:
        raise M0Error("Chromium host Clang returned no version")
    require_equal(
        "Chromium host Clang version",
        clang_version[0],
        str(clang_pin["version_output"]),
    )
    if str(clang_pin["llvm_revision"]) not in "\n".join(clang_version):
        raise M0Error("Chromium host LLVM revision mismatch")
    artifact_hashes = clang_pin["artifact_sha256"]
    assert isinstance(artifact_hashes, dict)
    for name in ("clang", "ld.lld", "llvm-ar"):
        artifact = clang_root / "bin" / name
        if not artifact.is_file():
            raise M0Error(f"Chromium host Clang is missing {name}")
        require_equal(
            f"Chromium host Clang artifact {name}",
            sha256(artifact),
            str(artifact_hashes[name]),
        )


def ensure_host_sysroot(
    manifest: dict[str, object],
    bootstrap_python: Path,
    *,
    install: bool,
) -> None:
    sysroot_pin = manifest["host_sysroot"]
    assert isinstance(sysroot_pin, dict)
    metadata_path = REPO_ROOT / str(sysroot_pin["metadata_path"])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    sysroot_key = (
        f"{sysroot_pin['platform']}_{sysroot_pin['arch']}"
    )
    source_pin = metadata.get(sysroot_key)
    if not isinstance(source_pin, dict):
        raise M0Error(f"Chromium sysroot pin is missing: {sysroot_key}")

    require_equal(
        "Chromium host sysroot path",
        (Path("build/linux") / str(source_pin["SysrootDir"])).as_posix(),
        str(sysroot_pin["path"]),
    )
    require_equal(
        "Chromium host sysroot tarball",
        str(source_pin["Tarball"]),
        str(sysroot_pin["tarball"]),
    )
    require_equal(
        "Chromium host sysroot URL",
        str(source_pin["URL"]),
        str(sysroot_pin["url"]),
    )
    require_equal(
        "Chromium host sysroot hash",
        str(source_pin["Sha256Sum"]),
        str(sysroot_pin["sha256"]),
    )

    install_script = (
        REPO_ROOT / "build/linux/sysroot_scripts/install-sysroot.py"
    )
    if install:
        run(
            [
                str(bootstrap_python),
                str(install_script),
                f"--arch={sysroot_pin['arch']}",
            ],
            capture_output=False,
        )

    sysroot = REPO_ROOT / str(sysroot_pin["path"])
    stamp = sysroot / ".stamp"
    if not sysroot.is_dir() or not stamp.is_file():
        raise M0Error("pinned Chromium host sysroot is not installed")
    expected_stamp = f"{sysroot_pin['url']}/{sysroot_pin['sha256']}"
    require_equal(
        "Chromium host sysroot stamp",
        stamp.read_text(encoding="utf-8"),
        expected_stamp,
    )
    for relative_path in (
        "usr/include/stdlib.h",
        "usr/lib/x86_64-linux-gnu/crt1.o",
    ):
        if not (sysroot / relative_path).is_file():
            raise M0Error(
                f"Chromium host sysroot is missing {relative_path}"
            )


def ensure_emscripten(
    manifest: dict[str, object],
    bootstrap_python: Path,
    *,
    install: bool,
) -> None:
    emscripten = manifest["emscripten"]
    assert isinstance(emscripten, dict)
    emsdk = REPO_ROOT / "third_party/emsdk"
    expected_revision = str(emscripten["emsdk_revision"])

    emsdk_created = False
    if install and not (emsdk / ".git").exists():
        run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--depth=1",
                "--branch",
                str(emscripten["emsdk_ref"]),
                str(emscripten["emsdk_remote"]),
                str(emsdk),
            ],
            capture_output=False,
        )
        emsdk_created = True
    if not (emsdk / ".git").exists():
        raise M0Error("pinned emsdk checkout is not installed")

    actual_revision = checked_output(["git", "rev-parse", "HEAD"], cwd=emsdk)
    require_equal("emsdk checkout", actual_revision, expected_revision)
    if not emsdk_created:
        require_equal(
            "emsdk worktree",
            checked_output(["git", "status", "--short"], cwd=emsdk),
            "",
        )

    releases_path = emsdk / "emscripten-releases-tags.json"
    releases = json.loads(releases_path.read_text(encoding="utf-8"))
    require_equal(
        "Emscripten release bundle",
        releases["releases"][str(emscripten["sdk_version"])],
        str(emscripten["release_bundle"]),
    )

    emcc = emsdk / "upstream/emscripten/emcc"
    if install:
        run(
            [
                str(bootstrap_python),
                "emsdk.py",
                "install",
                str(emscripten["sdk_version"]),
            ],
            cwd=emsdk,
            capture_output=False,
        )
        run(
            [
                str(bootstrap_python),
                "emsdk.py",
                "activate",
                str(emscripten["sdk_version"]),
            ],
            cwd=emsdk,
            capture_output=False,
        )
    if not emcc.is_file():
        raise M0Error("pinned Emscripten SDK is not installed")
    emscripten_config = emsdk / ".emscripten"
    if not emscripten_config.is_file():
        raise M0Error("activated Emscripten configuration is missing")
    require_equal(
        "Emscripten configuration hash",
        sha256(emscripten_config),
        str(emscripten["config_sha256"]),
    )

    require_equal(
        "Emscripten version",
        json.loads(
            (
                emsdk / "upstream/emscripten/emscripten-version.txt"
            ).read_text(encoding="utf-8")
        ),
        str(emscripten["sdk_version"]),
    )
    require_equal(
        "Emscripten source revision",
        (
            emsdk / "upstream/emscripten/emscripten-revision.txt"
        ).read_text(encoding="utf-8").strip(),
        str(emscripten["source_revision"]),
    )

    clang_version = run([str(emsdk / "upstream/bin/clang"), "--version"]).stdout
    if str(emscripten["llvm_revision"]) not in clang_version:
        raise M0Error("LLVM revision mismatch")

    wasm_opt_version = run(
        [str(emsdk / "upstream/bin/wasm-opt"), "--version"]
    ).stdout
    if str(emscripten["binaryen_version"]) not in wasm_opt_version:
        raise M0Error("Binaryen version mismatch")
    if str(emscripten["binaryen_revision"])[:9] not in wasm_opt_version:
        raise M0Error("Binaryen revision mismatch")

    node = (
        emsdk
        / "node"
        / f"{emscripten['node_version']}_64bit"
        / "bin/node"
    )
    require_equal(
        "Node version",
        checked_output([str(node), "--version"]),
        f"v{emscripten['node_version']}",
    )
    artifact_paths = {
        "emcc": emcc,
        "emcc.py": emsdk / "upstream/emscripten/emcc.py",
        "clang": emsdk / "upstream/bin/clang",
        "wasm-ld": emsdk / "upstream/bin/wasm-ld",
        "wasm-opt": emsdk / "upstream/bin/wasm-opt",
        "node": node,
    }
    artifact_hashes = emscripten["artifact_sha256"]
    assert isinstance(artifact_hashes, dict)
    for name, path in artifact_paths.items():
        require_equal(
            f"Emscripten artifact {name}",
            sha256(path),
            str(artifact_hashes[name]),
        )


def dawn_lastchange_paths(
    lastchange: dict[str, object],
) -> tuple[Path, Path]:
    configured_paths = (
        (
            "revision_path",
            "gpu/webgpu/DAWN_VERSION",
            "Dawn revision",
        ),
        (
            "header_path",
            "gpu/webgpu/dawn_commit_hash.h",
            "Dawn commit header",
        ),
    )
    repository_root = REPO_ROOT.resolve()
    paths: list[Path] = []
    for field, expected_value, label in configured_paths:
        configured_path = PurePosixPath(str(lastchange[field]))
        expected_path = PurePosixPath(expected_value)
        if configured_path != expected_path:
            raise M0Error(
                f"{label} path mismatch: expected {expected_path}, "
                f"got {configured_path}"
            )
        path = REPO_ROOT.joinpath(*configured_path.parts)
        try:
            path.parent.resolve().relative_to(repository_root)
        except ValueError as exc:
            raise M0Error(
                f"{label} path escapes the repository: {configured_path}"
            ) from exc
        if path.is_symlink():
            raise M0Error(f"{label} path must not be a symlink")
        paths.append(path)
    return paths[0], paths[1]


def verify_dawn_lastchange_deps_hook(
    manifest: dict[str, object],
) -> None:
    lastchange = manifest["dawn_lastchange"]
    dependencies = manifest["git_dependencies"]
    assert isinstance(lastchange, dict)
    assert isinstance(dependencies, dict)
    dependency_name = str(lastchange["dependency"])
    if dependency_name != "dawn":
        raise M0Error(
            "Dawn lastchange dependency mismatch: expected dawn, "
            f"got {dependency_name}"
        )
    dependency = dependencies[dependency_name]
    assert isinstance(dependency, dict)
    revision = str(lastchange["revision"])
    upstream_revision = str(
        dependency.get("upstream_revision", dependency["revision"])
    )
    require_equal("Dawn lastchange revision pin", revision, upstream_revision)
    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise M0Error(
            "Dawn lastchange revision must be a lowercase "
            "40-character Git hash"
        )

    revision_path, header_path = dawn_lastchange_paths(lastchange)
    version_macro = str(lastchange["version_macro"])
    if version_macro != "DAWN_COMMIT_HASH":
        raise M0Error(
            "Dawn lastchange macro mismatch: expected DAWN_COMMIT_HASH, "
            f"got {version_macro}"
        )

    deps_lines = (REPO_ROOT / "DEPS").read_text(
        encoding="utf-8"
    ).splitlines()
    marker = "'name': 'lastchange_dawn',"
    marker_lines = [
        index
        for index, line in enumerate(deps_lines)
        if line.strip() == marker
    ]
    if len(marker_lines) != 1:
        raise M0Error(
            "Chromium DEPS must contain exactly one lastchange_dawn hook"
        )
    start = marker_lines[0]
    while start >= 0 and deps_lines[start].strip() != "{":
        start -= 1
    end = marker_lines[0]
    while end < len(deps_lines) and deps_lines[end].strip() != "},":
        end += 1
    if start < 0 or end == len(deps_lines):
        raise M0Error("Chromium DEPS lastchange_dawn hook is malformed")
    hook_text = "\n".join(deps_lines[start : end + 1])

    source_path = PurePosixPath("src") / str(dependency["path"])
    expected_fields = (
        "'pattern': '.'",
        "'action': ['python3', 'src/build/util/lastchange.py'",
        f"'-m', '{version_macro}'",
        f"'-s', '{source_path}'",
        f"'--revision', 'src/{revision_path.relative_to(REPO_ROOT)}'",
        f"'--header', 'src/{header_path.relative_to(REPO_ROOT)}'",
    )
    for expected in expected_fields:
        if hook_text.count(expected) != 1:
            raise M0Error(
                "Chromium DEPS lastchange_dawn hook is missing "
                f"{expected}"
            )


def dawn_lastchange_contents(
    manifest: dict[str, object],
) -> tuple[str, str]:
    lastchange = manifest["dawn_lastchange"]
    assert isinstance(lastchange, dict)
    revision = str(lastchange["revision"])
    version_macro = str(lastchange["version_macro"])
    header = (
        "/* Generated by lastchange.py, do not edit.*/\n"
        "\n"
        "#ifndef GPU_WEBGPU_DAWN_COMMIT_HASH_H_\n"
        "#define GPU_WEBGPU_DAWN_COMMIT_HASH_H_\n"
        "\n"
        f'#define {version_macro} "{revision}"\n'
        "\n"
        "#endif  // GPU_WEBGPU_DAWN_COMMIT_HASH_H_\n"
    )
    return revision, header


def ensure_dawn_lastchange(
    manifest: dict[str, object], *, install: bool
) -> None:
    verify_dawn_lastchange_deps_hook(manifest)
    lastchange = manifest["dawn_lastchange"]
    assert isinstance(lastchange, dict)
    revision_path, header_path = dawn_lastchange_paths(lastchange)
    revision, header = dawn_lastchange_contents(manifest)
    artifacts = (
        ("generated Dawn revision", revision_path, revision),
        ("generated Dawn commit header", header_path, header),
    )

    if install:
        for label, path, expected_contents in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not path.is_file():
                raise M0Error(f"{label} path is not a regular file")
            if (
                not path.exists()
                or path.read_text(encoding="utf-8") != expected_contents
            ):
                path.write_text(expected_contents, encoding="utf-8")

    for label, path, expected_contents in artifacts:
        if path.is_symlink() or not path.is_file():
            raise M0Error(
                f"{path.relative_to(REPO_ROOT)} has not been generated"
            )
        require_equal(
            label,
            path.read_text(encoding="utf-8"),
            expected_contents,
        )


def ensure_generated_configuration(
    manifest: dict[str, object], *, install: bool
) -> None:
    generated_gclient_args = REPO_ROOT / "build/config/gclient_args.gni"
    gclient_template = Path(__file__).with_name("gclient_args.gni")
    expected_gclient_args = gclient_template.read_text(encoding="utf-8")
    chromium = manifest["chromium"]
    assert isinstance(chromium, dict)
    commit_timestamp = int(chromium["commit_timestamp"])
    commit_position = str(chromium["commit_position"])
    lastchange_revision = f"{chromium['revision']}-{commit_position}"
    lastchange_year = datetime.datetime.fromtimestamp(
        commit_timestamp, datetime.timezone.utc
    ).year
    generated_lastchange = REPO_ROOT / "build/util/LASTCHANGE"
    expected_lastchange = (
        f"LASTCHANGE={lastchange_revision}\n"
        f"LASTCHANGE_YEAR={lastchange_year}\n"
    )
    generated_lastchange_time = REPO_ROOT / "build/util/LASTCHANGE.committime"
    expected_lastchange_time = str(commit_timestamp)
    out_profiles = (
        (
            "generated Wasm GN args",
            REPO_ROOT / "out/wasm/args.gn",
            gn_args_text(manifest),
        ),
        (
            "generated M2 V8 GN args",
            REPO_ROOT / "out/wasm-v8-m2/args.gn",
            gn_args_text(manifest, "m2_v8_gn_args"),
        ),
        (
            "generated M3 Content GN args",
            REPO_ROOT / "out/wasm-content-m3/args.gn",
            gn_args_text(manifest, "m3_content_gn_args"),
        ),
    )

    if install:
        generated_gclient_args.parent.mkdir(parents=True, exist_ok=True)
        if (
            not generated_gclient_args.exists()
            or generated_gclient_args.read_text(encoding="utf-8")
            != expected_gclient_args
        ):
            shutil.copyfile(gclient_template, generated_gclient_args)
        for _, out_args, expected_out_args in out_profiles:
            out_args.parent.mkdir(parents=True, exist_ok=True)
            if (
                not out_args.exists()
                or out_args.read_text(encoding="utf-8") != expected_out_args
            ):
                out_args.write_text(expected_out_args, encoding="utf-8")
        generated_lastchange.parent.mkdir(parents=True, exist_ok=True)
        if (
            not generated_lastchange.exists()
            or generated_lastchange.read_text(encoding="utf-8")
            != expected_lastchange
        ):
            generated_lastchange.write_text(
                expected_lastchange, encoding="utf-8"
            )
        if (
            not generated_lastchange_time.exists()
            or generated_lastchange_time.read_text(encoding="utf-8")
            != expected_lastchange_time
        ):
            generated_lastchange_time.write_text(
                expected_lastchange_time, encoding="utf-8"
            )

    if not generated_gclient_args.exists():
        raise M0Error("build/config/gclient_args.gni has not been generated")
    require_equal(
        "generated gclient args",
        generated_gclient_args.read_text(encoding="utf-8"),
        expected_gclient_args,
    )
    for description, out_args, expected_out_args in out_profiles:
        if not out_args.exists():
            raise M0Error(
                f"{relative_to_repo(out_args)} has not been generated"
            )
        require_equal(
            description,
            out_args.read_text(encoding="utf-8"),
            expected_out_args,
        )
    if not generated_lastchange.exists():
        raise M0Error("build/util/LASTCHANGE has not been generated")
    require_equal(
        "generated Chromium LASTCHANGE",
        generated_lastchange.read_text(encoding="utf-8"),
        expected_lastchange,
    )
    if not generated_lastchange_time.exists():
        raise M0Error("build/util/LASTCHANGE.committime has not been generated")
    require_equal(
        "generated Chromium LASTCHANGE timestamp",
        generated_lastchange_time.read_text(encoding="utf-8"),
        expected_lastchange_time,
    )


def verify_rust_deps_pin(manifest: dict[str, object]) -> None:
    rust = manifest["rust"]
    assert isinstance(rust, dict)
    archive = str(rust["archive"])
    object_name = f"Linux_x64/{archive}"
    expected_url = (
        "https://commondatastorage.googleapis.com/"
        f"chromium-browser-clang/{object_name}"
    )
    require_equal("Chromium Rust archive URL", str(rust["url"]), expected_url)

    deps_text = (REPO_ROOT / "DEPS").read_text(encoding="utf-8")
    for expected in (
        "'bucket': 'chromium-browser-clang'",
        f"'object_name': '{object_name}'",
        f"'sha256sum': '{rust['sha256']}'",
        f"'size_bytes': {rust['size_bytes']},",
    ):
        if expected not in deps_text:
            raise M0Error(f"Chromium DEPS is missing Rust pin {expected}")


def read_python_constant(path: Path, name: str) -> object:
    prefix = f"{name} = "
    assignments = [
        line.removeprefix(prefix)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    if len(assignments) != 1:
        raise M0Error(f"{path} must define exactly one {name}")
    try:
        return ast.literal_eval(assignments[0])
    except (SyntaxError, ValueError) as exc:
        raise M0Error(f"{path} has an invalid {name}") from exc


def verify_rust_source_pins(
    manifest: dict[str, object], rust: dict[str, object]
) -> None:
    rust_update = REPO_ROOT / "tools/rust/update_rust.py"
    clang_update = REPO_ROOT / "tools/clang/scripts/update.py"
    require_equal(
        "Chromium Rust source revision",
        str(read_python_constant(rust_update, "RUST_REVISION")),
        str(rust["source_revision"]),
    )
    require_equal(
        "Chromium Rust package subrevision",
        str(read_python_constant(rust_update, "RUST_SUB_REVISION")),
        str(rust["subrevision"]),
    )
    require_equal(
        "Chromium Clang revision used by Rust",
        str(read_python_constant(clang_update, "CLANG_REVISION")),
        str(rust["clang_revision"]),
    )
    require_equal(
        "Chromium Clang package subrevision",
        str(read_python_constant(clang_update, "CLANG_SUB_REVISION")),
        str(rust["clang_subrevision"]),
    )
    expected_package_revision = (
        f"{rust['source_revision']}-{rust['subrevision']}-"
        f"{rust['clang_revision']}"
    )
    require_equal(
        "Chromium Rust package revision",
        str(rust["package_revision"]),
        expected_package_revision,
    )
    require_equal(
        "Chromium Rust compiler commit",
        str(rust["commit_hash"]),
        str(rust["source_revision"]),
    )
    expected_stamp_suffix = f"({rust['package_revision']} chromium)"
    if not str(rust["version_line"]).endswith(expected_stamp_suffix):
        raise M0Error("Chromium Rust VERSION does not contain the package pin")
    rustc_vv = rust["rustc_vv"]
    assert isinstance(rustc_vv, dict)
    if not str(rustc_vv["version"]).endswith(expected_stamp_suffix):
        raise M0Error(
            "Chromium rustc -Vv version does not contain the package pin"
        )
    host_clang = manifest["host_clang"]
    assert isinstance(host_clang, dict)
    require_equal(
        "Chromium Rust host Clang package revision",
        str(host_clang["revision"]),
        f"{rust['clang_revision']}-{rust['clang_subrevision']}",
    )


def rust_toolchain_path(rust: dict[str, object]) -> Path:
    configured_path = Path(str(rust["path"]))
    if configured_path.is_absolute() or ".." in configured_path.parts:
        raise M0Error("Chromium Rust toolchain path must stay in the checkout")
    expected_path = Path("third_party/rust-toolchain")
    if configured_path != expected_path:
        raise M0Error(
            "Chromium Rust toolchain path mismatch: "
            f"expected {expected_path}, got {configured_path}"
        )
    return REPO_ROOT / configured_path


def parse_rustc_verbose_version(output: str) -> dict[str, str]:
    lines = output.splitlines()
    if not lines or not lines[0].startswith("rustc "):
        raise M0Error("pinned Chromium rustc returned an invalid -Vv header")
    fields = {"version": lines[0]}
    for line in lines[1:]:
        name, separator, value = line.partition(": ")
        if not separator or not name or not value:
            raise M0Error("pinned Chromium rustc returned invalid -Vv output")
        if name in fields:
            raise M0Error(
                f"pinned Chromium rustc repeated -Vv field {name}"
            )
        fields[name] = value
    return fields


def verify_rust_toolchain(
    rust: dict[str, object], toolchain_root: Path
) -> None:
    if not toolchain_root.is_dir():
        raise M0Error("pinned Chromium Rust toolchain is not installed")

    version_path = toolchain_root / "VERSION"
    rustc = toolchain_root / "bin/rustc"
    if not version_path.is_file() or not rustc.is_file():
        raise M0Error(
            "pinned Chromium Rust toolchain is missing VERSION or bin/rustc"
        )

    require_equal(
        "Chromium Rust VERSION",
        version_path.read_text(encoding="utf-8").strip(),
        str(rust["version_line"]),
    )

    verbose_version = parse_rustc_verbose_version(
        checked_output([str(rustc), "-Vv"])
    )
    expected_verbose_version = rust["rustc_vv"]
    assert isinstance(expected_verbose_version, dict)
    for name, expected_value in expected_verbose_version.items():
        require_equal(
            f"Chromium rustc -Vv {name}",
            verbose_version.get(str(name), ""),
            str(expected_value),
        )
    require_equal(
        "Chromium rustc commit",
        verbose_version.get("commit-hash", ""),
        str(rust["commit_hash"]),
    )
    require_equal(
        "Chromium rustc host",
        verbose_version.get("host", ""),
        str(rust["host_target"]),
    )

    target_list = set(
        checked_output([str(rustc), "--print", "target-list"]).splitlines()
    )
    required_targets = rust["required_targets"]
    assert isinstance(required_targets, list)
    for target in required_targets:
        if str(target) not in target_list:
            raise M0Error(
                f"pinned Chromium rustc is missing target {target}"
            )

    reported_sysroot = Path(
        checked_output([str(rustc), "--print", "sysroot"])
    )
    require_equal(
        "Chromium rustc sysroot",
        str(reported_sysroot.resolve()),
        str(toolchain_root.resolve()),
    )

    rustc_src_files = rust["rustc_src_files"]
    assert isinstance(rustc_src_files, list)
    for relative_path in rustc_src_files:
        source_path = toolchain_root / str(relative_path)
        if not source_path.is_file() or source_path.stat().st_size == 0:
            raise M0Error(
                f"pinned Chromium Rust source is missing {relative_path}"
            )


def download_rust_archive(
    rust: dict[str, object], archive_path: Path
) -> None:
    expected_size = int(rust["size_bytes"])
    request = urllib.request.Request(
        str(rust["url"]),
        headers={"User-Agent": "chromium-wasm-bootstrap/1"},
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            archive_path.open("xb") as output_file,
        ):
            shutil.copyfileobj(response, output_file, 1024 * 1024)
    except (OSError, urllib.error.URLError) as exc:
        raise M0Error(
            f"failed to download pinned Chromium Rust archive: {exc}"
        ) from exc

    require_equal(
        "Chromium Rust archive size",
        str(archive_path.stat().st_size),
        str(expected_size),
    )
    require_equal(
        "Chromium Rust archive hash",
        sha256(archive_path),
        str(rust["sha256"]),
    )


def install_rust_toolchain(
    rust: dict[str, object], toolchain_root: Path
) -> None:
    if os.path.lexists(toolchain_root):
        try:
            verify_rust_toolchain(rust, toolchain_root)
        except M0Error as exc:
            raise M0Error(
                "existing Chromium Rust toolchain is invalid; "
                f"refusing to overwrite it: {exc}"
            ) from exc
        return

    toolchain_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{toolchain_root.name}.install-",
            dir=toolchain_root.parent,
        )
    )
    archive_path = staging_root / str(rust["archive"])
    candidate_root = staging_root / "toolchain"
    candidate_root.mkdir()
    try:
        download_rust_archive(rust, archive_path)
        try:
            with tarfile.open(archive_path, mode="r:xz") as archive:
                archive.extractall(candidate_root, filter="data")
        except (OSError, tarfile.TarError) as exc:
            raise M0Error(
                f"failed to extract pinned Chromium Rust archive: {exc}"
            ) from exc
        verify_rust_toolchain(rust, candidate_root)
        if os.path.lexists(toolchain_root):
            raise M0Error(
                "Chromium Rust toolchain path appeared during installation"
            )
        os.replace(candidate_root, toolchain_root)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def ensure_rust_toolchain(
    manifest: dict[str, object], *, install: bool
) -> None:
    rust = manifest["rust"]
    assert isinstance(rust, dict)
    verify_rust_deps_pin(manifest)
    verify_rust_source_pins(manifest, rust)
    toolchain_root = rust_toolchain_path(rust)
    if install:
        install_rust_toolchain(rust, toolchain_root)
    else:
        verify_rust_toolchain(rust, toolchain_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Install or verify exact Chromium Wasm milestone source and "
            "toolchain pins."
        )
    )
    parser.add_argument(
        "--profile",
        choices=("m0", "m3"),
        default="m0",
        help="select the exact milestone source dependency closure",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="perform no installs or generated-file writes",
    )
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        print_context(
            "bootstrap.py",
            manifest,
            mode=(
                f"{'verify-only' if args.verify_only else 'install'}:"
                f"{args.profile}"
            ),
        )
        install = not args.verify_only
        required_submodules = (
            M0_REQUIRED_SUBMODULES
            if args.profile == "m0"
            else M3_REQUIRED_SUBMODULES
        )
        ensure_source_dependencies(
            manifest,
            install=install,
            required_submodules=required_submodules,
        )
        if args.profile == "m3":
            ensure_nested_source_dependencies(manifest, install=install)
            ensure_dawn_lastchange(manifest, install=install)
        ensure_test262(manifest, install=install)
        cipd, bootstrap_python = ensure_depot_tools_bootstrap(
            manifest, install=install
        )
        ensure_build_tools(manifest, cipd, install=install)
        if args.profile == "m3":
            ensure_chromium_node_runtime(manifest, install=install)
            ensure_webui_node_modules(manifest, install=install)
        ensure_host_clang(
            manifest, bootstrap_python, install=install
        )
        ensure_host_sysroot(
            manifest, bootstrap_python, install=install
        )
        ensure_emscripten(
            manifest, bootstrap_python, install=install
        )
        ensure_generated_configuration(manifest, install=install)
        ensure_rust_toolchain(manifest, install=install)
        print(
            f"CHROMIUM_WASM_{args.profile.upper()}:BOOTSTRAP_PASS",
            flush=True,
        )
        return 0
    except (M0Error, KeyError, TypeError, ValueError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())

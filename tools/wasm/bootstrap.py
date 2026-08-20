#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import ast
import datetime
import fcntl
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
    "dom_distiller_js",
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
    "quic_trace",
    "re2",
    "search_engines_data",
    "smhasher",
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


EMSCRIPTEN_SOURCE_PIN_FIELDS = frozenset(
    (
        "source_remote",
        "source_ref",
        "source_revision",
        "source_version",
        "source_file_sha256",
        "source_npm_tree_sha256",
    )
)
EMSCRIPTEN_SOURCE_PIN_OPTIONAL_FIELDS = (
    EMSCRIPTEN_SOURCE_PIN_FIELDS - {"source_revision"}
)
EMSCRIPTEN_SOURCE_CACHE = Path("out/wasm-emscripten-cache")
EMSCRIPTEN_SOURCE_LOCK = Path("out/wasm-emscripten-source.lock")

# Exact Unix output paths from Emscripten 5.0.6's
# tools/maint/create_entry_points.py when invoked without arguments on Linux.
# Keep this static rather than executing or parsing untrusted source to decide
# which paths the generator may overwrite.
EMSCRIPTEN_SOURCE_ENTRY_POINT_OUTPUTS = (
    "emcc",
    "em++",
    "bootstrap",
    "emar",
    "embuilder",
    "emcmake",
    "em-config",
    "emconfigure",
    "emmake",
    "emranlib",
    "emrun",
    "emscons",
    "emsize",
    "emprofile",
    "emdwp",
    "emnm",
    "emstrip",
    "emsymbolizer",
    "emscan-deps",
    "empath-split",
    "tools/file_packager",
    "tools/webidl_binder",
    "test/runner",
)


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


def is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


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


def ensure_chromium_sysroot(
    manifest: dict[str, object],
    bootstrap_python: Path,
    *,
    manifest_key: str,
    label: str,
    install: bool,
) -> None:
    sysroot_pin = manifest[manifest_key]
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
        f"Chromium {label} sysroot path",
        (Path("build/linux") / str(source_pin["SysrootDir"])).as_posix(),
        str(sysroot_pin["path"]),
    )
    require_equal(
        f"Chromium {label} sysroot tarball",
        str(source_pin["Tarball"]),
        str(sysroot_pin["tarball"]),
    )
    require_equal(
        f"Chromium {label} sysroot URL",
        str(source_pin["URL"]),
        str(sysroot_pin["url"]),
    )
    require_equal(
        f"Chromium {label} sysroot hash",
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
        raise M0Error(
            f"pinned Chromium {label} sysroot is not installed"
        )
    expected_stamp = f"{sysroot_pin['url']}/{sysroot_pin['sha256']}"
    require_equal(
        f"Chromium {label} sysroot stamp",
        stamp.read_text(encoding="utf-8"),
        expected_stamp,
    )
    library_arch = {
        "amd64": "x86_64-linux-gnu",
        "i386": "i386-linux-gnu",
    }.get(str(sysroot_pin["arch"]))
    if library_arch is None:
        raise M0Error(
            f"unsupported Chromium {label} sysroot architecture: "
            f"{sysroot_pin['arch']}"
        )
    for relative_path in (
        "usr/include/stdlib.h",
        f"usr/lib/{library_arch}/crt1.o",
    ):
        if not (sysroot / relative_path).is_file():
            raise M0Error(
                f"Chromium {label} sysroot is missing {relative_path}"
            )


def ensure_host_sysroot(
    manifest: dict[str, object],
    bootstrap_python: Path,
    *,
    install: bool,
) -> None:
    ensure_chromium_sysroot(
        manifest,
        bootstrap_python,
        manifest_key="host_sysroot",
        label="host",
        install=install,
    )


def verify_pinned_runtime_package(
    package: dict[str, object], archive_path: Path
) -> None:
    label = f"V8 snapshot runtime {package['name']}"
    if archive_path.is_symlink() or not archive_path.is_file():
        raise M0Error(f"pinned {label} package is not installed")
    require_equal(
        f"{label} package size",
        str(archive_path.stat().st_size),
        str(package["size_bytes"]),
    )
    require_equal(
        f"{label} package SHA-256",
        sha256(archive_path),
        str(package["sha256"]),
    )


def download_pinned_runtime_package(
    package: dict[str, object], archive_path: Path
) -> None:
    label = f"V8 snapshot runtime {package['name']}"
    request = urllib.request.Request(
        str(package["url"]),
        headers={"User-Agent": "chromium-wasm-bootstrap/1"},
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            archive_path.open("xb") as output_file,
        ):
            copied = 0
            expected_size = int(package["size_bytes"])
            while chunk := response.read(1024 * 1024):
                copied += len(chunk)
                if copied > expected_size:
                    raise M0Error(
                        f"pinned {label} package exceeds "
                        f"{expected_size} bytes"
                    )
                output_file.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        raise M0Error(f"failed to download pinned {label}: {exc}") from exc
    verify_pinned_runtime_package(package, archive_path)


def v8_snapshot_runtime_stamp(runtime: dict[str, object]) -> str:
    packages = runtime["packages"]
    assert isinstance(packages, list)
    return "".join(
        f"{package['name']} {package['sha256']}\n"
        for package in packages
        if isinstance(package, dict)
    )


def v8_snapshot_runtime_path(runtime: dict[str, object]) -> Path:
    configured_root = Path(str(runtime["path"]))
    expected_root = Path("out/wasm-i386-runtime/root")
    if configured_root != expected_root:
        raise M0Error(
            "V8 snapshot runtime path mismatch: expected "
            f"{expected_root}, got {configured_root}"
        )
    output_root = REPO_ROOT / "out"
    runtime_parent = REPO_ROOT / expected_root.parent
    for path in (output_root, runtime_parent):
        if path.is_symlink():
            raise M0Error(
                f"V8 snapshot runtime parent must not be a symlink: {path}"
            )
        try:
            path.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError as exc:
            raise M0Error(
                "V8 snapshot runtime must stay inside the checkout"
            ) from exc
    return REPO_ROOT / expected_root


def v8_snapshot_package_archive_path(
    runtime: dict[str, object], package: dict[str, object]
) -> Path:
    configured_archive = Path(str(package["archive_path"]))
    expected_parent = Path(str(runtime["path"])).parent
    if (
        configured_archive.is_absolute()
        or configured_archive.parent != expected_parent
        or configured_archive.suffix != ".deb"
    ):
        raise M0Error(
            "V8 snapshot runtime package path must be a .deb directly "
            f"under {expected_parent}: {configured_archive}"
        )
    archive_path = REPO_ROOT / configured_archive
    try:
        archive_path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise M0Error(
            "V8 snapshot runtime package must stay inside the checkout"
        ) from exc
    return archive_path


def verify_v8_snapshot_runtime(
    runtime: dict[str, object],
    *,
    runtime_root: Path | None = None,
    verify_execution: bool = True,
) -> None:
    configured_runtime_root = v8_snapshot_runtime_path(runtime)
    if runtime_root is None:
        runtime_root = configured_runtime_root
    if runtime_root.is_symlink() or not runtime_root.is_dir():
        raise M0Error("pinned V8 snapshot runtime is not installed")

    packages = runtime["packages"]
    assert isinstance(packages, list)
    package_list_relative = Path(str(runtime["package_list_path"]))
    if package_list_relative != Path(
        "build/linux/sysroot_scripts/generated_package_lists/bullseye.i386"
    ):
        raise M0Error("V8 snapshot runtime package list path mismatch")
    package_list_path = REPO_ROOT / package_list_relative
    if package_list_path.is_symlink() or not package_list_path.is_file():
        raise M0Error("Chromium i386 package list is missing")
    package_urls = package_list_path.read_text(
        encoding="utf-8"
    ).splitlines()
    for raw_package in packages:
        assert isinstance(raw_package, dict)
        package = raw_package
        if package_urls.count(str(package["url"])) != 1:
            raise M0Error(
                "Chromium i386 package list must contain exactly one "
                f"{package['name']} runtime pin"
            )
        archive_path = v8_snapshot_package_archive_path(runtime, package)
        verify_pinned_runtime_package(package, archive_path)

    stamp = runtime_root / ".stamp"
    if stamp.is_symlink() or not stamp.is_file():
        raise M0Error("pinned V8 snapshot runtime stamp is missing")
    require_equal(
        "V8 snapshot runtime stamp",
        stamp.read_text(encoding="utf-8"),
        v8_snapshot_runtime_stamp(runtime),
    )

    artifacts = runtime["artifacts"]
    assert isinstance(artifacts, dict)
    for relative_path, expected_hash in artifacts.items():
        artifact = runtime_root / str(relative_path)
        if artifact.is_symlink() or not artifact.is_file():
            raise M0Error(
                f"V8 snapshot runtime is missing {relative_path}"
            )
        require_equal(
            f"V8 snapshot runtime {relative_path}",
            sha256(artifact),
            str(expected_hash),
        )

    symlinks = runtime["symlinks"]
    assert isinstance(symlinks, dict)
    for relative_path, expected_target in symlinks.items():
        symlink = runtime_root / str(relative_path)
        if not symlink.is_symlink():
            raise M0Error(
                f"V8 snapshot runtime is missing symlink {relative_path}"
            )
        require_equal(
            f"V8 snapshot runtime symlink {relative_path}",
            os.readlink(symlink),
            str(expected_target),
        )

    loader = runtime_root / str(runtime["loader_path"])
    if verify_execution:
        library_paths = runtime["library_paths"]
        if library_paths != ["lib/i386-linux-gnu"]:
            raise M0Error("V8 snapshot runtime library path mismatch")
        library_directory = runtime_root / str(library_paths[0])
        libc_version = run(
            [
                str(loader),
                "--library-path",
                str(library_directory),
                str(library_directory / "libc.so.6"),
            ]
        ).stdout.splitlines()
        if not libc_version:
            raise M0Error("V8 snapshot runtime libc returned no version")
        require_equal(
            "V8 snapshot runtime libc version",
            libc_version[0],
            "GNU C Library (Debian GLIBC 2.31-13+deb11u5) "
            "stable release version 2.31.",
        )


def install_v8_snapshot_runtime(runtime: dict[str, object]) -> None:
    runtime_root = v8_snapshot_runtime_path(runtime)
    packages = runtime["packages"]
    assert isinstance(packages, list)
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    if runtime_root.parent.is_symlink():
        raise M0Error("V8 snapshot runtime parent must not be a symlink")

    for raw_package in packages:
        assert isinstance(raw_package, dict)
        package = raw_package
        archive_path = v8_snapshot_package_archive_path(runtime, package)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(archive_path):
            staging_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{package['name']}.download-",
                    dir=archive_path.parent,
                )
            )
            candidate_archive = staging_root / archive_path.name
            try:
                download_pinned_runtime_package(
                    package, candidate_archive
                )
                if os.path.lexists(archive_path):
                    raise M0Error(
                        "V8 snapshot runtime package path appeared "
                        f"during installation: {archive_path}"
                    )
                os.replace(candidate_archive, archive_path)
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)
        verify_pinned_runtime_package(package, archive_path)

    if os.path.lexists(runtime_root):
        verify_v8_snapshot_runtime(runtime)
        return

    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb is None:
        raise M0Error(
            "dpkg-deb is required to install the V8 snapshot runtime"
        )
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=".runtime.install-",
            dir=runtime_root.parent,
        )
    )
    candidate_root = staging_root / "root"
    candidate_root.mkdir()
    try:
        for raw_package in packages:
            assert isinstance(raw_package, dict)
            archive_path = v8_snapshot_package_archive_path(
                runtime, raw_package
            )
            run(
                [
                    dpkg_deb,
                    "--extract",
                    str(archive_path),
                    str(candidate_root),
                ],
                capture_output=False,
            )
        (candidate_root / ".stamp").write_text(
            v8_snapshot_runtime_stamp(runtime),
            encoding="utf-8",
        )
        verify_v8_snapshot_runtime(
            runtime,
            runtime_root=candidate_root,
        )
        if os.path.lexists(runtime_root):
            raise M0Error(
                "V8 snapshot runtime path appeared during installation"
            )
        os.replace(candidate_root, runtime_root)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def ensure_v8_snapshot_runtime(
    manifest: dict[str, object], *, install: bool
) -> None:
    runtime = manifest["v8_snapshot_runtime"]
    assert isinstance(runtime, dict)
    if install:
        install_v8_snapshot_runtime(runtime)
    else:
        verify_v8_snapshot_runtime(runtime)


def emscripten_source_pin(
    emscripten: dict[str, object],
) -> dict[str, object] | None:
    """Return an optional immutable Emscripten source-fork pin.

    The normal emsdk release bundle remains the default. A source fork is an
    all-or-nothing opt-in because mixing a mutable branch name with a release
    source revision would make the bootstrap non-reproducible.
    """
    unexpected_fields = {
        field
        for field in emscripten
        if field.startswith("source_")
        and field
        not in EMSCRIPTEN_SOURCE_PIN_FIELDS
    }
    if unexpected_fields:
        raise M0Error(
            "unknown Emscripten source fork fields: "
            + ", ".join(sorted(unexpected_fields))
        )

    configured_optional_fields = {
        field
        for field in EMSCRIPTEN_SOURCE_PIN_OPTIONAL_FIELDS
        if field in emscripten
    }
    if not configured_optional_fields:
        return None
    configured_fields = {
        field for field in EMSCRIPTEN_SOURCE_PIN_FIELDS if field in emscripten
    }
    if configured_fields != EMSCRIPTEN_SOURCE_PIN_FIELDS:
        raise M0Error(
            "Emscripten source fork fields must be configured together: "
            + ", ".join(sorted(EMSCRIPTEN_SOURCE_PIN_FIELDS))
        )

    remote = emscripten["source_remote"]
    if (
        not isinstance(remote, str)
        or not remote.strip()
        or "\0" in remote
    ):
        raise M0Error("Emscripten source fork remote must be a nonempty string")

    source_ref = emscripten["source_ref"]
    source_revision = emscripten["source_revision"]
    if not is_lower_hex(source_ref, 40):
        raise M0Error(
            "Emscripten source fork ref must be a lowercase 40-character "
            "Git hash"
        )
    if not is_lower_hex(source_revision, 40):
        raise M0Error(
            "Emscripten source revision must be a lowercase 40-character "
            "Git hash"
        )
    require_equal(
        "Emscripten source fork ref",
        str(source_ref),
        str(source_revision),
    )

    source_version = emscripten["source_version"]
    if (
        not isinstance(source_version, str)
        or not source_version
        or source_version != source_version.strip()
    ):
        raise M0Error(
            "Emscripten source fork version must be a nonempty trimmed string"
        )

    npm_tree_sha256 = emscripten["source_npm_tree_sha256"]
    if not is_lower_hex(npm_tree_sha256, 64):
        raise M0Error(
            "Emscripten source fork npm tree hash must be a lowercase "
            "SHA-256"
        )

    raw_file_hashes = emscripten["source_file_sha256"]
    if not isinstance(raw_file_hashes, dict) or not raw_file_hashes:
        raise M0Error(
            "Emscripten source fork file hashes must be a nonempty object"
        )
    file_hashes: dict[str, str] = {}
    for raw_path, raw_hash in raw_file_hashes.items():
        if not isinstance(raw_path, str):
            raise M0Error("Emscripten source fork file path must be a string")
        path = PurePosixPath(raw_path)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in (".", "..") for part in path.parts)
            or path.as_posix() != raw_path
        ):
            raise M0Error(
                "Emscripten source fork file path must be a relative "
                f"canonical POSIX path: {raw_path}"
            )
        if not is_lower_hex(raw_hash, 64):
            raise M0Error(
                "Emscripten source fork file hash must be a lowercase "
                f"SHA-256: {raw_path}"
            )
        file_hashes[raw_path] = str(raw_hash)

    return {
        "remote": remote,
        "ref": source_ref,
        "revision": source_revision,
        "version": source_version,
        "file_hashes": file_hashes,
        "npm_tree_sha256": npm_tree_sha256,
    }


def emscripten_source_file(root: Path, relative_path: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    if path.is_symlink() or not path.is_file():
        raise M0Error(f"Emscripten source is missing {relative_path}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise M0Error(
            "Emscripten source file escapes its distribution root: "
            f"{relative_path}"
        ) from exc
    return path


def verify_emscripten_source_entry_point_outputs(root: Path) -> None:
    """Preflight every 5.0.6 Unix launcher output before generation.

    The upstream checkout contains a tracked regular ``bootstrap`` launcher,
    so regular leaf files are allowed. Symlinks, directories, and special
    files are rejected before the generator can overwrite them. Every parent
    component must be a non-symlink directory confined to the checkout.
    """
    if root.is_symlink() or not root.is_dir():
        raise M0Error("Emscripten source entry-point root is not a directory")
    root_resolved = root.resolve()
    for relative_path in EMSCRIPTEN_SOURCE_ENTRY_POINT_OUTPUTS:
        path_parts = PurePosixPath(relative_path).parts
        parent = root
        for component in path_parts[:-1]:
            parent /= component
            if parent.is_symlink() or not parent.is_dir():
                raise M0Error(
                    "Emscripten source entry-point parent is not a "
                    f"non-symlink directory: {relative_path}"
                )
            try:
                parent.resolve().relative_to(root_resolved)
            except ValueError as exc:
                raise M0Error(
                    "Emscripten source entry-point parent escapes its "
                    f"checkout: {relative_path}"
                ) from exc

        output = parent / path_parts[-1]
        if not os.path.lexists(output):
            continue
        if output.is_symlink() or not stat.S_ISREG(output.stat().st_mode):
            raise M0Error(
                "Emscripten source entry-point output is not a regular file: "
                + relative_path
            )


def emscripten_source_executable(root: Path, relative_path: str) -> Path:
    """Return a regular, readable, executable Emscripten source launcher."""
    path = emscripten_source_file(root, relative_path)
    if not stat.S_ISREG(path.stat().st_mode) or not os.access(
        path, os.R_OK | os.X_OK
    ):
        raise M0Error(
            "Emscripten source launcher is not a regular executable: "
            + relative_path
        )
    return path


def normalize_emscripten_source_launcher(
    root: Path, relative_path: str
) -> Path:
    """Make a generated compiler launcher usable regardless of the umask."""
    path = emscripten_source_file(root, relative_path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise M0Error(
            "Emscripten source launcher is not a regular executable: "
            + relative_path
        )
    try:
        path.chmod(0o755)
    except OSError as exc:
        raise M0Error(
            "cannot normalize generated Emscripten source launcher: "
            + relative_path
        ) from exc
    return emscripten_source_executable(root, relative_path)


def emscripten_source_version(root: Path) -> str:
    version_path = emscripten_source_file(root, "emscripten-version.txt")
    contents = version_path.read_text(encoding="utf-8")
    try:
        json_version = json.loads(contents)
    except json.JSONDecodeError:
        # emsdk release bundles use a JSON string while source-fork install
        # output may carry the upstream plain-text version marker. Accept only
        # one canonical plain-text line, never arbitrary malformed JSON.
        version = contents.removesuffix("\n")
        if (
            not version
            or not version[0].isdigit()
            or contents not in (version, version + "\n")
            or any(
                character not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz._+-"
                for character in version
            )
        ):
            raise M0Error("Emscripten source version file is invalid")
        return version
    if not isinstance(json_version, str):
        raise M0Error("Emscripten source version file must contain a string")
    return json_version


def emscripten_release_version(root: Path) -> str:
    """Read the official emsdk release marker without accepting fork syntax."""
    version_path = emscripten_source_file(root, "emscripten-version.txt")
    try:
        version = json.loads(version_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise M0Error("Emscripten release version file is invalid JSON") from exc
    if not isinstance(version, str):
        raise M0Error("Emscripten release version file must contain a string")
    return version


def emscripten_artifact_hash(
    emscripten: dict[str, object], name: str
) -> str:
    artifact_hashes = emscripten["artifact_sha256"]
    if not isinstance(artifact_hashes, dict):
        raise M0Error("Emscripten artifact hashes must be an object")
    expected_hash = artifact_hashes.get(name)
    if not is_lower_hex(expected_hash, 64):
        raise M0Error(
            "Emscripten artifact hash must be a lowercase SHA-256: "
            f"{name}"
        )
    return str(expected_hash)


def verify_emscripten_source_tree(
    source_pin: dict[str, object], root: Path
) -> None:
    if root.is_symlink() or not root.is_dir():
        raise M0Error("pinned Emscripten source tree is not installed")
    require_equal(
        "Emscripten source version",
        emscripten_source_version(root),
        str(source_pin["version"]),
    )
    file_hashes = source_pin["file_hashes"]
    assert isinstance(file_hashes, dict)
    for relative_path, expected_hash in file_hashes.items():
        path = emscripten_source_file(root, str(relative_path))
        require_equal(
            f"Emscripten source file {relative_path}",
            sha256(path),
            str(expected_hash),
        )


def verify_emscripten_source_checkout(
    source_pin: dict[str, object], checkout_root: Path
) -> None:
    if checkout_root.is_symlink() or not (checkout_root / ".git").is_dir():
        raise M0Error("pinned Emscripten source checkout is not installed")
    require_equal(
        "Emscripten source checkout root",
        str(
            Path(
                checked_output(
                    ["git", "rev-parse", "--show-toplevel"],
                    cwd=checkout_root,
                )
            ).resolve()
        ),
        str(checkout_root.resolve()),
    )
    require_equal(
        "Emscripten source checkout",
        checked_output(
            ["git", "rev-parse", "HEAD^{commit}"], cwd=checkout_root
        ),
        str(source_pin["revision"]),
    )
    require_equal(
        "Emscripten source HEAD",
        checked_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=checkout_root,
        ),
        "HEAD",
    )
    require_equal(
        "Emscripten source origin",
        checked_output(
            ["git", "remote", "get-url", "--all", "origin"],
            cwd=checkout_root,
        ),
        str(source_pin["remote"]),
    )
    require_equal(
        "Emscripten source worktree",
        checked_output(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=checkout_root,
        ),
        "",
    )
    verify_emscripten_source_tree(source_pin, checkout_root)


def verify_emscripten_source_distribution(
    source_pin: dict[str, object],
    emscripten: dict[str, object],
    distribution_root: Path,
) -> None:
    verify_emscripten_source_tree(source_pin, distribution_root)
    revision_path = emscripten_source_file(
        distribution_root, "emscripten-revision.txt"
    )
    require_equal(
        "Emscripten source revision",
        revision_path.read_text(encoding="utf-8").strip(),
        str(source_pin["revision"]),
    )
    for name in ("emcc", "em++"):
        path = emscripten_source_executable(distribution_root, name)
        require_equal(
            f"Emscripten source artifact {name}",
            sha256(path),
            emscripten_artifact_hash(emscripten, name),
        )
    for name in ("emcc.py", "em++.py"):
        path = emscripten_source_file(distribution_root, name)
        require_equal(
            f"Emscripten source artifact {name}",
            sha256(path),
            emscripten_artifact_hash(emscripten, name),
        )


def emscripten_binary_artifact_paths(
    emscripten: dict[str, object], emsdk: Path
) -> dict[str, Path]:
    node = (
        emsdk
        / "node"
        / f"{emscripten['node_version']}_64bit"
        / "bin/node"
    )
    return {
        "clang": emsdk / "upstream/bin/clang",
        "wasm-ld": emsdk / "upstream/bin/wasm-ld",
        "wasm-opt": emsdk / "upstream/bin/wasm-opt",
        "node": node,
    }


def verify_emscripten_binary_artifacts(
    emscripten: dict[str, object], emsdk: Path
) -> None:
    for name, path in emscripten_binary_artifact_paths(
        emscripten, emsdk
    ).items():
        if not path.is_file():
            raise M0Error(f"pinned Emscripten artifact is missing: {name}")
        require_equal(
            f"Emscripten artifact {name}",
            sha256(path),
            emscripten_artifact_hash(emscripten, name),
        )


def emscripten_npm_execution_closure_sha256(node: Path) -> str:
    """Hash the pinned npm launcher and all JavaScript it can load.

    ``tools/install.py`` executes ``npm ci``.  The Node executable already has
    a manifest hash, but a hash for Node alone says nothing about the mutable
    npm launcher and its bundled package tree.  Reject symlinks below the npm
    tree so the closure cannot silently escape the pinned SDK directory.
    """
    if node.is_symlink() or not node.is_file() or not os.access(node, os.X_OK):
        raise M0Error("pinned Emscripten Node executable is not a regular file")
    node_root = node.parent.parent
    if node_root.is_symlink() or not node_root.is_dir():
        raise M0Error("pinned Emscripten Node root is not a directory")
    node_root_resolved = node_root.resolve()
    bin_directory = node.parent
    lib_directory = node_root / "lib"
    node_modules_directory = lib_directory / "node_modules"
    for label, directory in (
        ("bin", bin_directory),
        ("lib", lib_directory),
        ("node_modules", node_modules_directory),
    ):
        if directory.is_symlink() or not directory.is_dir():
            raise M0Error(
                "pinned Emscripten Node " + label + " directory is invalid"
            )
        try:
            directory.resolve().relative_to(node_root_resolved)
        except ValueError as exc:
            raise M0Error(
                "pinned Emscripten Node " + label + " directory escapes its root"
            ) from exc
    try:
        node.resolve().relative_to(node_root_resolved)
    except ValueError as exc:
        raise M0Error("pinned Emscripten Node executable escapes its root") from exc
    launcher = node.parent / "npm"
    npm_root = node_modules_directory / "npm"
    if npm_root.is_symlink() or not npm_root.is_dir():
        raise M0Error("pinned Emscripten npm package is not installed")
    try:
        npm_root.resolve().relative_to(node_root_resolved)
    except ValueError as exc:
        raise M0Error("pinned Emscripten npm package escapes its Node root") from exc
    if not os.path.lexists(launcher):
        raise M0Error("pinned Emscripten npm launcher is not installed")

    digest = hashlib.sha256()

    def update_text(value: str) -> None:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")

    update_text("chromium-wasm-emscripten-npm-closure-v1")
    for label, directory in (
        ("node-root", node_root),
        ("node-bin", bin_directory),
        ("node-lib", lib_directory),
        ("node-modules", node_modules_directory),
        ("npm-root", npm_root),
    ):
        update_text(label + "-mode")
        update_text(oct(directory.stat().st_mode & 0o777))
    update_text("node-mode")
    update_text(oct(node.stat().st_mode & 0o777))
    if launcher.is_symlink():
        launcher_target = launcher.resolve()
        try:
            launcher_target.relative_to(npm_root.resolve())
        except ValueError as exc:
            raise M0Error("pinned Emscripten npm launcher escapes its package") from exc
        update_text("launcher-symlink")
        update_text(os.readlink(launcher))
        if not launcher_target.is_file() or not os.access(launcher_target, os.X_OK):
            raise M0Error("pinned Emscripten npm launcher is not executable")
        update_text("launcher-target-mode")
        update_text(oct(launcher_target.stat().st_mode & 0o777))
    elif launcher.is_file() and os.access(launcher, os.X_OK):
        update_text("launcher-file")
        update_text("launcher-mode")
        update_text(oct(launcher.stat().st_mode & 0o777))
        digest.update(bytes.fromhex(sha256(launcher)))
    else:
        raise M0Error("pinned Emscripten npm launcher is not a file")

    for path in sorted(npm_root.rglob("*"), key=lambda item: item.as_posix()):
        relative_path = path.relative_to(node_root).as_posix()
        if path.is_symlink():
            raise M0Error(
                "pinned Emscripten npm package must not contain symlinks: "
                + relative_path
            )
        if path.is_dir():
            update_text("directory")
            update_text(relative_path)
            update_text(oct(path.stat().st_mode & 0o777))
            continue
        if not path.is_file():
            raise M0Error(
                "pinned Emscripten npm package has an unsupported entry: "
                + relative_path
            )
        update_text("file")
        update_text(relative_path)
        update_text(oct(path.stat().st_mode & 0o777))
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def verify_emscripten_npm_execution_closure(
    source_pin: dict[str, object], node: Path
) -> Path:
    require_equal(
        "Emscripten npm execution closure",
        emscripten_npm_execution_closure_sha256(node),
        str(source_pin["npm_tree_sha256"]),
    )
    return node.parent


def emscripten_source_installer_path(staging_root: Path, node: Path) -> Path:
    """Create a minimal PATH with only the verified installer executables."""
    tools_root = staging_root / "installer-tools"
    tools_root.mkdir()

    def host_executable(name: str) -> Path:
        value = shutil.which(name)
        if value is None:
            raise M0Error(f"required host executable is unavailable: {name}")
        path = Path(value).resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise M0Error(f"required host executable is not executable: {name}")
        return path

    npm = node.parent / "npm"
    npm_target = npm.resolve()
    if not npm_target.is_file() or not os.access(npm_target, os.X_OK):
        raise M0Error("pinned Emscripten npm launcher is not executable")
    executables = {
        "node": node.resolve(),
        "npm": npm_target,
        # Emscripten's source installer records the source revision with Git.
        # Bootstrap already relies on the host Git binary to fetch/verify the
        # detached checkout, so expose that same executable explicitly rather
        # than preserving a mutable inherited PATH.
        "git": host_executable("git"),
        # npm may run shell hooks from its pinned package lock.
        "sh": host_executable("sh"),
    }
    for name, executable in executables.items():
        os.symlink(executable, tools_root / name)
    return tools_root


def emscripten_cache_path() -> Path:
    cache_path = REPO_ROOT / EMSCRIPTEN_SOURCE_CACHE
    try:
        cache_path.parent.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise M0Error("Emscripten cache path escapes the checkout") from exc
    return cache_path


def emscripten_source_lock_path() -> Path:
    lock_path = REPO_ROOT / EMSCRIPTEN_SOURCE_LOCK
    try:
        lock_path.parent.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise M0Error("Emscripten source lock path escapes the checkout") from exc
    return lock_path


def acquire_emscripten_source_update_lock() -> int:
    """Acquire the lock shared by the compiler driver during source promotion."""
    lock_path = emscripten_source_lock_path()
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise M0Error("cannot open Emscripten source update lock") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise M0Error("Emscripten source update lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        os.close(descriptor)
        raise M0Error("cannot acquire Emscripten source update lock") from exc
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def release_emscripten_source_update_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def remove_emscripten_source_recovery_path(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if not path.is_dir():
        raise M0Error("Emscripten source recovery path is not removable")
    shutil.rmtree(path)


def has_emscripten_source_recovery_copy(staging_root: Path) -> bool:
    return any(
        os.path.lexists(staging_root / name)
        for name in ("previous-distribution", "previous-cache")
    )


def promote_emscripten_source_distribution(
    candidate_root: Path,
    distribution_root: Path,
    staging_root: Path,
    cache_path: Path,
) -> None:
    """Promote a verified source only while compilers are excluded."""
    update_lock = acquire_emscripten_source_update_lock()
    try:
        _promote_emscripten_source_distribution(
            candidate_root, distribution_root, staging_root, cache_path
        )
    finally:
        release_emscripten_source_update_lock(update_lock)


def _promote_emscripten_source_distribution(
    candidate_root: Path,
    distribution_root: Path,
    staging_root: Path,
    cache_path: Path,
) -> None:
    """Atomically promote source and invalidate its cache, or preserve recovery.

    The active source is never removed until a verified candidate is present.
    If a source or cache rollback itself fails, retain the staging directory and
    its recovery copies rather than deleting the only remaining good SDK tree.
    The matching compiler driver takes a shared advisory lock, so supported
    GN builds drain before this source/cache hand-off. Direct or legacy emcc
    invocations do not participate and remain unsupported during promotion.
    """
    if candidate_root.is_symlink() or not candidate_root.is_dir():
        raise M0Error("staged Emscripten source distribution is invalid")
    if distribution_root.is_symlink() or not distribution_root.is_dir():
        raise M0Error("installed Emscripten source distribution is invalid")
    distribution_backup = staging_root / "previous-distribution"
    cache_backup = staging_root / "previous-cache"
    if os.path.lexists(distribution_backup) or os.path.lexists(cache_backup):
        raise M0Error("Emscripten source staging backup path already exists")

    candidate_promoted = False
    cache_moved = False
    try:
        os.replace(distribution_root, distribution_backup)
        if os.path.lexists(cache_path):
            os.replace(cache_path, cache_backup)
            cache_moved = True
        os.replace(candidate_root, distribution_root)
        candidate_promoted = True
    except BaseException as exc:
        # A signal can land between the two rename operations.  Derive whether
        # the source was already promoted from the on-disk state before trying
        # to restore anything; never replace a successful new distribution with
        # its old one merely because Python was interrupted at that boundary.
        source_appears_promoted = (
            os.path.lexists(distribution_root)
            and not os.path.lexists(candidate_root)
            and os.path.lexists(distribution_backup)
        )
        cache_appears_moved = (
            os.path.lexists(cache_backup) and not os.path.lexists(cache_path)
        )
        restoration_errors: list[BaseException] = []
        if not candidate_promoted and not source_appears_promoted:
            if os.path.lexists(distribution_backup) and not os.path.lexists(
                distribution_root
            ):
                try:
                    os.replace(distribution_backup, distribution_root)
                except BaseException as rollback_error:
                    restoration_errors.append(rollback_error)
        if not (source_appears_promoted or candidate_promoted) and (
            cache_moved or cache_appears_moved
        ) and os.path.lexists(cache_backup) and not os.path.lexists(cache_path):
            try:
                os.replace(cache_backup, cache_path)
            except BaseException as rollback_error:
                restoration_errors.append(rollback_error)
        if restoration_errors or source_appears_promoted or candidate_promoted:
            raise M0Error(
                "Emscripten source promotion was interrupted; recovery copies "
                "were preserved"
            ) from exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise M0Error(
            "cannot promote staged Emscripten source distribution; the "
            "previous distribution and cache were restored"
        ) from exc

    # Discard the old, now-incompatible cache only after the new source became
    # active.  If cleanup is interrupted, retain the backup for manual
    # recovery instead of risking data loss in the finally block.
    try:
        remove_emscripten_source_recovery_path(distribution_backup)
        if cache_moved:
            remove_emscripten_source_recovery_path(cache_backup)
    except BaseException as exc:
        try:
            # There is no safe rollback after the new distribution is active.
            # Leave any recovery copy in place and require an explicit retry.
            if not has_emscripten_source_recovery_copy(staging_root):
                raise M0Error("Emscripten source recovery copy disappeared")
        except M0Error:
            raise
        raise M0Error(
            "Emscripten source promotion completed but recovery cleanup was "
            "interrupted; recovery copies were preserved"
        ) from exc


def install_emscripten_source_pin(
    source_pin: dict[str, object],
    emscripten: dict[str, object],
    emsdk: Path,
    bootstrap_python: Path,
) -> None:
    distribution_root = emsdk / "upstream/emscripten"
    if distribution_root.parent.is_symlink():
        raise M0Error("Emscripten upstream directory must not be a symlink")
    if distribution_root.is_symlink() or not distribution_root.is_dir():
        raise M0Error("installed Emscripten source distribution is invalid")

    staging_root = Path(
        tempfile.mkdtemp(
            prefix=".emscripten-source-pin-",
            dir=distribution_root.parent,
        )
    )
    checkout_root = staging_root / "source"
    candidate_root = staging_root / "distribution"
    try:
        run(["git", "init", "--quiet", str(checkout_root)])
        run(
            ["git", "remote", "add", "origin", str(source_pin["remote"])],
            cwd=checkout_root,
        )
        run(
            [
                "git",
                "fetch",
                "--depth=1",
                "--no-tags",
                "origin",
                str(source_pin["ref"]),
            ],
            cwd=checkout_root,
            capture_output=False,
        )
        require_equal(
            "Emscripten source fetched revision",
            checked_output(
                ["git", "rev-parse", "FETCH_HEAD^{commit}"],
                cwd=checkout_root,
            ),
            str(source_pin["revision"]),
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
            cwd=checkout_root,
        )
        verify_emscripten_source_checkout(source_pin, checkout_root)

        entry_points_script = emscripten_source_file(
            checkout_root, "tools/maint/create_entry_points.py"
        )
        verify_emscripten_source_entry_point_outputs(checkout_root)
        entry_points_home = staging_root / "entry-points-home"
        entry_points_tmp = staging_root / "entry-points-tmp"
        entry_points_home.mkdir()
        entry_points_tmp.mkdir()

        # The source checkout's 5.0.6 entry-point generator may overwrite only
        # the static preflighted paths above. Run it with the pinned bootstrap
        # Python and no inherited environment before the source installer
        # copies generated compiler launchers into the candidate distribution.
        run(
            [str(bootstrap_python), str(entry_points_script)],
            cwd=checkout_root,
            capture_output=False,
            env={
                "HOME": str(entry_points_home),
                "TMPDIR": str(entry_points_tmp),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "LANG": "C",
                "LC_ALL": "C",
            },
            clear_env=True,
        )
        for launcher in ("emcc", "em++"):
            normalize_emscripten_source_launcher(checkout_root, launcher)
        verify_emscripten_source_checkout(source_pin, checkout_root)

        install_script = emscripten_source_file(
            checkout_root, "tools/install.py"
        )
        binary_artifacts = emscripten_binary_artifact_paths(
            emscripten, emsdk
        )
        node = binary_artifacts["node"]
        verify_emscripten_binary_artifacts(emscripten, emsdk)
        verify_emscripten_npm_execution_closure(source_pin, node)
        installer_tools = emscripten_source_installer_path(staging_root, node)
        installer_home = staging_root / "installer-home"
        installer_tmp = staging_root / "installer-tmp"
        installer_npm_cache = staging_root / "installer-npm-cache"
        installer_npm_user_config = staging_root / "installer-npmrc"
        installer_npm_global_config = staging_root / "installer-npm-globalrc"
        for path in (installer_home, installer_tmp, installer_npm_cache):
            path.mkdir()
        installer_npm_user_config.touch()
        installer_npm_global_config.touch()

        # Run the source-provided installer with an empty inherited environment.
        # In particular, never allow NODE_OPTIONS, NPM_CONFIG_*, or a host npm
        # launcher to influence the pinned source distribution.  The private
        # PATH contains only the verified SDK Node/npm pair and the explicit
        # host Git/sh executables needed by Emscripten's installer.
        run(
            [
                str(bootstrap_python),
                str(install_script),
                str(candidate_root),
            ],
            cwd=checkout_root,
            capture_output=False,
            env={
                "PATH": str(installer_tools),
                "HOME": str(installer_home),
                "TMPDIR": str(installer_tmp),
                "NPM_CONFIG_CACHE": str(installer_npm_cache),
                "NPM_CONFIG_USERCONFIG": str(installer_npm_user_config),
                "NPM_CONFIG_GLOBALCONFIG": str(installer_npm_global_config),
                "GIT_CONFIG_NOSYSTEM": "1",
                "LANG": "C",
                "LC_ALL": "C",
            },
            clear_env=True,
        )
        verify_emscripten_source_checkout(source_pin, checkout_root)
        verify_emscripten_source_distribution(
            source_pin, emscripten, candidate_root
        )

        # The candidate is fully verified before either the active source tree
        # or the driver-owned cache is touched. Promotion moves the exact cache
        # selected by build/toolchain/wasm/emscripten_driver.py into the same
        # recovery transaction as the source distribution.
        promote_emscripten_source_distribution(
            candidate_root,
            distribution_root,
            staging_root,
            emscripten_cache_path(),
        )
    finally:
        if not has_emscripten_source_recovery_copy(staging_root):
            shutil.rmtree(staging_root, ignore_errors=True)


def ensure_emscripten_source_pin(
    emscripten: dict[str, object],
    emsdk: Path,
    bootstrap_python: Path,
    *,
    install: bool,
) -> dict[str, object] | None:
    source_pin = emscripten_source_pin(emscripten)
    if source_pin is None:
        return None
    if install:
        install_emscripten_source_pin(
            source_pin, emscripten, emsdk, bootstrap_python
        )
    verify_emscripten_source_distribution(
        source_pin, emscripten, emsdk / "upstream/emscripten"
    )
    return source_pin


def ensure_pinned_emscripten_source_distribution(
    manifest: dict[str, object], *, install: bool
) -> None:
    """Install or verify only the immutable Emscripten source distribution.

    This deliberately does not call ``ensure_source_dependencies()``: it is a
    recovery path for an otherwise unrelated Chromium provenance failure, not
    a replacement for either normal M0 or M3 bootstrap. It still requires the
    installed, pinned depot_tools bootstrap and runs the complete Emscripten
    SDK/source-pin validation and promotion flow.
    """
    emscripten = manifest["emscripten"]
    assert isinstance(emscripten, dict)
    if emscripten_source_pin(emscripten) is None:
        raise M0Error(
            "Emscripten source-only mode requires a complete immutable "
            "source pin"
        )

    _, bootstrap_python = ensure_depot_tools_bootstrap(
        manifest, install=False
    )
    ensure_emscripten(manifest, bootstrap_python, install=install)


def ensure_emscripten(
    manifest: dict[str, object],
    bootstrap_python: Path,
    *,
    install: bool,
) -> None:
    emscripten = manifest["emscripten"]
    assert isinstance(emscripten, dict)
    requested_source_pin = emscripten_source_pin(emscripten)
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

    emscripten_root = emsdk / "upstream/emscripten"
    emcc = emscripten_root / "emcc"
    emxx = emscripten_root / "em++"
    if install:
        update_lock = (
            acquire_emscripten_source_update_lock()
            if requested_source_pin is not None
            else None
        )
        try:
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
        finally:
            if update_lock is not None:
                release_emscripten_source_update_lock(update_lock)
    source_pin = ensure_emscripten_source_pin(
        emscripten, emsdk, bootstrap_python, install=install
    )
    for launcher in ("emcc", "em++"):
        emscripten_source_executable(emscripten_root, launcher)
    emcc_py = emscripten_source_file(emscripten_root, "emcc.py")
    emxx_py = emscripten_source_file(emscripten_root, "em++.py")
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
        (
            emscripten_source_version
            if source_pin is not None
            else emscripten_release_version
        )(emsdk / "upstream/emscripten"),
        (
            str(source_pin["version"])
            if source_pin is not None
            else str(emscripten["sdk_version"])
        ),
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
        "em++": emxx,
        "emcc.py": emcc_py,
        "em++.py": emxx_py,
        "clang": emsdk / "upstream/bin/clang",
        "wasm-ld": emsdk / "upstream/bin/wasm-ld",
        "wasm-opt": emsdk / "upstream/bin/wasm-opt",
        "node": node,
    }
    for name, path in artifact_paths.items():
        require_equal(
            f"Emscripten artifact {name}",
            sha256(path),
            emscripten_artifact_hash(emscripten, name),
        )


def skia_lastchange_path(lastchange: dict[str, object]) -> Path:
    configured_path = PurePosixPath(str(lastchange["header_path"]))
    expected_path = PurePosixPath("skia/ext/skia_commit_hash.h")
    if configured_path != expected_path:
        raise M0Error(
            f"Skia commit header path mismatch: expected {expected_path}, "
            f"got {configured_path}"
        )
    repository_root = REPO_ROOT.resolve()
    path = REPO_ROOT.joinpath(*configured_path.parts)
    try:
        path.parent.resolve().relative_to(repository_root)
    except ValueError as exc:
        raise M0Error(
            "Skia commit header path escapes the repository: "
            f"{configured_path}"
        ) from exc
    if path.is_symlink():
        raise M0Error("Skia commit header path must not be a symlink")
    return path


def verify_skia_lastchange_deps_hook(
    manifest: dict[str, object],
) -> None:
    lastchange = manifest["skia_lastchange"]
    dependencies = manifest["git_dependencies"]
    assert isinstance(lastchange, dict)
    assert isinstance(dependencies, dict)
    dependency_name = str(lastchange["dependency"])
    if dependency_name != "skia":
        raise M0Error(
            "Skia lastchange dependency mismatch: expected skia, "
            f"got {dependency_name}"
        )
    dependency = dependencies[dependency_name]
    assert isinstance(dependency, dict)
    revision = str(lastchange["revision"])
    upstream_revision = str(
        dependency.get("upstream_revision", dependency["revision"])
    )
    require_equal("Skia lastchange revision pin", revision, upstream_revision)
    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise M0Error(
            "Skia lastchange revision must be a lowercase "
            "40-character Git hash"
        )

    header_path = skia_lastchange_path(lastchange)
    version_macro = str(lastchange["version_macro"])
    if version_macro != "SKIA_COMMIT_HASH":
        raise M0Error(
            "Skia lastchange macro mismatch: expected SKIA_COMMIT_HASH, "
            f"got {version_macro}"
        )

    deps_lines = (REPO_ROOT / "DEPS").read_text(
        encoding="utf-8"
    ).splitlines()
    marker = "'name': 'lastchange_skia',"
    marker_lines = [
        index
        for index, line in enumerate(deps_lines)
        if line.strip() == marker
    ]
    if len(marker_lines) != 1:
        raise M0Error(
            "Chromium DEPS must contain exactly one lastchange_skia hook"
        )
    start = marker_lines[0]
    while start >= 0 and deps_lines[start].strip() != "{":
        start -= 1
    end = marker_lines[0]
    while end < len(deps_lines) and deps_lines[end].strip() != "},":
        end += 1
    if start < 0 or end == len(deps_lines):
        raise M0Error("Chromium DEPS lastchange_skia hook is malformed")
    hook_text = "\n".join(deps_lines[start : end + 1])

    source_path = PurePosixPath("src") / str(dependency["path"])
    expected_fields = (
        "'pattern': '.'",
        "'action': ['python3', 'src/build/util/lastchange.py'",
        f"'-m', '{version_macro}'",
        f"'-s', '{source_path}'",
        f"'--header', 'src/{header_path.relative_to(REPO_ROOT)}'",
    )
    for expected in expected_fields:
        if hook_text.count(expected) != 1:
            raise M0Error(
                "Chromium DEPS lastchange_skia hook is missing "
                f"{expected}"
            )


def skia_lastchange_contents(manifest: dict[str, object]) -> str:
    lastchange = manifest["skia_lastchange"]
    assert isinstance(lastchange, dict)
    revision = str(lastchange["revision"])
    version_macro = str(lastchange["version_macro"])
    return (
        "/* Generated by lastchange.py, do not edit.*/\n"
        "\n"
        "#ifndef SKIA_EXT_SKIA_COMMIT_HASH_H_\n"
        "#define SKIA_EXT_SKIA_COMMIT_HASH_H_\n"
        "\n"
        f'#define {version_macro} "{revision}"\n'
        "\n"
        "#endif  // SKIA_EXT_SKIA_COMMIT_HASH_H_\n"
    )


def ensure_skia_lastchange(
    manifest: dict[str, object], *, install: bool
) -> None:
    verify_skia_lastchange_deps_hook(manifest)
    lastchange = manifest["skia_lastchange"]
    assert isinstance(lastchange, dict)
    header_path = skia_lastchange_path(lastchange)
    header = skia_lastchange_contents(manifest)

    if install:
        header_path.parent.mkdir(parents=True, exist_ok=True)
        if header_path.exists() and not header_path.is_file():
            raise M0Error(
                "generated Skia commit header path is not a regular file"
            )
        if (
            not header_path.exists()
            or header_path.read_text(encoding="utf-8") != header
        ):
            header_path.write_text(header, encoding="utf-8")

    if header_path.is_symlink() or not header_path.is_file():
        raise M0Error(
            f"{header_path.relative_to(REPO_ROOT)} has not been generated"
        )
    require_equal(
        "generated Skia commit header",
        header_path.read_text(encoding="utf-8"),
        header,
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
        (
            "generated M6 Chrome GN args",
            REPO_ROOT / "out/wasm-chrome-m6/args.gn",
            gn_args_text(manifest, "m6_chrome_gn_args"),
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
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--profile",
        choices=("m0", "m3"),
        default="m0",
        help="select the exact milestone source dependency closure",
    )
    mode_group.add_argument(
        "--emscripten-source-only",
        action="store_true",
        help=(
            "install or verify only the immutable pinned Emscripten source "
            "distribution; does not validate Chromium/dependency provenance "
            "or constitute a full bootstrap"
        ),
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="perform no installs or generated-file writes",
    )
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        install = not args.verify_only
        if args.emscripten_source_only:
            source_only_action = "verify-only" if args.verify_only else "install"
            print_context(
                "bootstrap.py",
                manifest,
                mode=f"{source_only_action}:emscripten-source-only",
                scope="pinned-emscripten-source-distribution-only",
                full_bootstrap=False,
            )
            ensure_pinned_emscripten_source_distribution(
                manifest, install=install
            )
            print(
                "CHROMIUM_WASM_EMSCRIPTEN_SOURCE_ONLY:"
                "PINNED_SOURCE_DISTRIBUTION_PASS "
                f"mode={source_only_action}",
                flush=True,
            )
            return 0

        print_context(
            "bootstrap.py",
            manifest,
            mode=(
                f"{'verify-only' if args.verify_only else 'install'}:"
                f"{args.profile}"
            ),
        )
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
            ensure_skia_lastchange(manifest, install=install)
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
        if args.profile == "m3":
            ensure_chromium_sysroot(
                manifest,
                bootstrap_python,
                manifest_key="v8_snapshot_sysroot",
                label="V8 snapshot",
                install=install,
            )
            ensure_v8_snapshot_runtime(manifest, install=install)
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

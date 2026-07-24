#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
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


REQUIRED_SUBMODULES = (
    "v8",
    "angle",
    "compiler_rt",
    "depot_tools",
    "perfetto",
    "protobuf_javascript",
    "googletest",
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


def gitlink_revision(base_revision: str, path: str) -> str:
    entry = checked_output(["git", "ls-tree", base_revision, "--", path])
    fields = entry.split()
    if len(fields) < 3 or fields[1] != "commit":
        raise M0Error(f"{path} is not a gitlink at the Chromium base revision")
    return fields[2]


def ensure_source_dependencies(
    manifest: dict[str, object], *, install: bool
) -> None:
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

    if install:
        paths = [
            str(dependencies[name]["path"])  # type: ignore[index]
            for name in REQUIRED_SUBMODULES
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

    for name in REQUIRED_SUBMODULES:
        dependency = dependencies[name]
        assert isinstance(dependency, dict)
        dependency_path = REPO_ROOT / str(dependency["path"])
        if not (dependency_path / ".git").exists():
            raise M0Error(f"required dependency is not initialized: {name}")
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


def ensure_build_tools(
    manifest: dict[str, object], cipd: Path, *, install: bool
) -> None:
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


def ensure_generated_configuration(
    manifest: dict[str, object], *, install: bool
) -> None:
    generated_gclient_args = REPO_ROOT / "build/config/gclient_args.gni"
    gclient_template = Path(__file__).with_name("gclient_args.gni")
    expected_gclient_args = gclient_template.read_text(encoding="utf-8")
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
    )

    if install and not generated_gclient_args.exists():
        generated_gclient_args.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gclient_template, generated_gclient_args)
    if install:
        for _, out_args, expected_out_args in out_profiles:
            if not out_args.exists():
                out_args.parent.mkdir(parents=True, exist_ok=True)
                out_args.write_text(expected_out_args, encoding="utf-8")

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
        description="Install or verify the exact M0 source and toolchain pins."
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
            mode="verify-only" if args.verify_only else "install",
        )
        install = not args.verify_only
        ensure_source_dependencies(manifest, install=install)
        ensure_test262(manifest, install=install)
        cipd, bootstrap_python = ensure_depot_tools_bootstrap(
            manifest, install=install
        )
        ensure_build_tools(manifest, cipd, install=install)
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
        print("CHROMIUM_WASM_M0:BOOTSTRAP_PASS", flush=True)
        return 0
    except (M0Error, KeyError, TypeError, ValueError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())

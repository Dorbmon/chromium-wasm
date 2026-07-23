#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys

from m0_common import (
    M0Error,
    REPO_ROOT,
    checked_output,
    fail,
    gn_args_text,
    load_manifest,
    print_context,
    run,
)


REQUIRED_SUBMODULES = ("v8", "angle", "depot_tools")


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
        require_equal(
            f"{name} gitlink",
            gitlink_revision(base_revision, str(raw_dependency["path"])),
            str(raw_dependency["revision"]),
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
    out_args = REPO_ROOT / "out/wasm/args.gn"
    expected_out_args = gn_args_text(manifest)

    if install and not generated_gclient_args.exists():
        generated_gclient_args.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gclient_template, generated_gclient_args)
    if install and not out_args.exists():
        out_args.parent.mkdir(parents=True, exist_ok=True)
        out_args.write_text(expected_out_args, encoding="utf-8")

    if not generated_gclient_args.exists():
        raise M0Error("build/config/gclient_args.gni has not been generated")
    require_equal(
        "generated gclient args",
        generated_gclient_args.read_text(encoding="utf-8"),
        expected_gclient_args,
    )
    if not out_args.exists():
        raise M0Error("out/wasm/args.gn has not been generated")
    require_equal(
        "generated Wasm GN args",
        out_args.read_text(encoding="utf-8"),
        expected_out_args,
    )


def verify_rust_pin(manifest: dict[str, object]) -> None:
    rust = manifest["rust"]
    assert isinstance(rust, dict)
    deps_text = (REPO_ROOT / "DEPS").read_text(encoding="utf-8")
    for expected in (str(rust["archive"]), str(rust["sha256"])):
        if expected not in deps_text:
            raise M0Error(f"Chromium DEPS is missing Rust pin {expected}")


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
        cipd, bootstrap_python = ensure_depot_tools_bootstrap(
            manifest, install=install
        )
        ensure_build_tools(manifest, cipd, install=install)
        ensure_emscripten(
            manifest, bootstrap_python, install=install
        )
        ensure_generated_configuration(manifest, install=install)
        verify_rust_pin(manifest)
        print("CHROMIUM_WASM_M0:BOOTSTRAP_PASS", flush=True)
        return 0
    except (M0Error, KeyError, TypeError, ValueError) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())

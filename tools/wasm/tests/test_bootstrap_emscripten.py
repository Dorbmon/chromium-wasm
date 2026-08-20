#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Focused tests for optional immutable Emscripten source-fork bootstrap."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import bootstrap
from m0_common import M0Error, load_manifest


EXPECTED_ENTRY_POINT_OUTPUTS = (
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

EXPECTED_M7_OPFS_SOURCE_FILES = frozenset(
    (
        "src/lib/libdylink.js",
        "src/lib/libpthread.js",
        "src/lib/libsigs.js",
        "src/lib/libsyscall.js",
        "src/lib/libwasmfs.js",
        "src/lib/libwasmfs_node.js",
        "src/lib/libwasmfs_opfs.js",
        "src/settings.js",
        "system/include/emscripten/wasmfs.h",
        "system/include/emscripten/wasmfs_opfs_profile_drain.h",
        "system/include/emscripten/wasmfs_terminal_drain.h",
        "system/lib/libc/emscripten_libc_stubs.c",
        "system/lib/libc/emscripten_mmap.c",
        "system/lib/wasmfs/backend.h",
        "system/lib/wasmfs/backends/fetch_backend.cpp",
        "system/lib/wasmfs/backends/ignore_case_backend.cpp",
        "system/lib/wasmfs/backends/js_file_backend.cpp",
        "system/lib/wasmfs/backends/memory_backend.cpp",
        "system/lib/wasmfs/backends/node_backend.cpp",
        "system/lib/wasmfs/backends/opfs_backend.cpp",
        "system/lib/wasmfs/backends/opfs_backend.h",
        "system/lib/wasmfs/emscripten.cpp",
        "system/lib/wasmfs/file.cpp",
        "system/lib/wasmfs/file.h",
        "system/lib/wasmfs/file_table.cpp",
        "system/lib/wasmfs/file_table.h",
        "system/lib/wasmfs/js_api.cpp",
        "system/lib/wasmfs/js_impl_backend.h",
        "system/lib/wasmfs/paths.cpp",
        "system/lib/wasmfs/pipe_backend.h",
        "system/lib/wasmfs/syscalls.cpp",
        "system/lib/wasmfs/thread_utils.h",
        "system/lib/wasmfs/wasmfs.cpp",
        "system/lib/wasmfs/wasmfs.h",
        "tools/emscripten.py",
        "tools/link.py",
        "tools/system_libs.py",
    )
)

EXPECTED_M7_OPFS_SOURCE_FILE_HASHES_SHA256 = (
    "237c24a8929b68ec68f4944b19f61b6d078515baa93ba60ab004a57a51d1dcc5"
)


def run_git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def source_installer_contents() -> str:
    return """\
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

source_root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1])
target.mkdir()
for relative_path in (
    "emscripten-version.txt",
    "emcc",
    "em++",
    "emcc.py",
    "em++.py",
    "system/lib/wasmfs/syscalls.cpp",
):
    source = source_root / relative_path
    destination = target / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
(target / "source-launchers.json").write_text(
    json.dumps(
        {
            name: {
                "mode": stat.S_IMODE((source_root / name).stat().st_mode),
                "readable": os.access(source_root / name, os.R_OK),
                "executable": os.access(source_root / name, os.X_OK),
            }
            for name in ("emcc", "em++")
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
(target / "installer-path.txt").write_text(
    os.environ["PATH"], encoding="utf-8"
)
(target / "installer-npm-config.txt").write_text(
    os.environ["NPM_CONFIG_USERCONFIG"] + "\\n" +
    os.environ["NPM_CONFIG_GLOBALCONFIG"] + "\\n",
    encoding="utf-8",
)
npm = shutil.which("npm")
if npm is None:
    raise RuntimeError("pinned npm is unavailable")
(target / "resolved-npm.txt").write_text(npm + "\\n", encoding="utf-8")
subprocess.check_call([npm, "ci", "--omit=dev"], cwd=target)
revision = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=source_root, text=True
).strip()
(target / "emscripten-revision.txt").write_text(
    revision + "\\n", encoding="utf-8"
)
"""


def entry_points_contents(
    emcc_contents: bytes,
    emcc_execute_bits: int,
    emxx_contents: bytes,
    emxx_execute_bits: int,
    *,
    generate_emxx: bool,
    generator_umask: int | None,
) -> str:
    return f"""\\
import os
from pathlib import Path
import stat

expected_environment = {{
    "HOME",
    "TMPDIR",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONHASHSEED",
    "LANG",
    "LC_ALL",
}}
if set(os.environ) != expected_environment:
    raise RuntimeError("entry-point generator received an inherited environment")
if os.environ["PYTHONDONTWRITEBYTECODE"] != "1":
    raise RuntimeError("entry-point generator may write bytecode")
if os.environ["PYTHONHASHSEED"] != "0":
    raise RuntimeError("entry-point generator hash seed is not deterministic")
if os.environ["LANG"] != "C" or os.environ["LC_ALL"] != "C":
    raise RuntimeError("entry-point generator locale is not deterministic")

source_root = Path(__file__).resolve().parents[2]
generator_umask = {generator_umask!r}
if generator_umask is not None:
    os.umask(generator_umask)
launchers = {{
    "emcc": ({emcc_contents!r}, {emcc_execute_bits:#o}),
    "em++": ({emxx_contents!r}, {emxx_execute_bits:#o}),
}}
if not {generate_emxx!r}:
    del launchers["em++"]
for name, (contents, execute_bits) in launchers.items():
    launcher = source_root / name
    launcher.write_bytes(contents)
    launcher.chmod(stat.S_IMODE(launcher.stat().st_mode) | execute_bits)
"""


def npm_cli_contents() -> str:
    return f"""\
#!{sys.executable}
from pathlib import Path
import sys

if sys.argv[1:] != ["ci", "--omit=dev"]:
    raise SystemExit("unexpected npm invocation")
Path.cwd().joinpath("npm-ci.txt").write_text("ok\\n", encoding="utf-8")
"""


def create_source_origin(
    root: Path,
    *,
    emcc_execute_bits: int = 0o111,
    emxx_execute_bits: int = 0o111,
    generate_emxx: bool = True,
    generator_umask: int | None = None,
    tracked_entry_point_symlink: str | None = None,
    tracked_entry_point_symlink_target: Path | None = None,
) -> tuple[Path, str, dict[str, bytes]]:
    origin = root / "source-origin"
    origin.mkdir()
    run_git(origin, "init", "--quiet")
    emcc_contents = b"#!/bin/sh\nexit 0\n"
    emxx_contents = b"#!/bin/sh\nexit 0\n"
    files = {
        ".gitignore": b"emcc\nem++\n",
        "emscripten-version.txt": b"5.0.6-git\n",
        "bootstrap": b"tracked bootstrap launcher\n",
        "emcc.py": b"fork emcc.py\n",
        "em++.py": b"fork em++.py\n",
        "system/lib/wasmfs/syscalls.cpp": b"fork fcntl locks\n",
        "test/fixture.txt": b"entry-point parent fixture\n",
        "tools/maint/create_entry_points.py": entry_points_contents(
            emcc_contents,
            emcc_execute_bits,
            emxx_contents,
            emxx_execute_bits,
            generate_emxx=generate_emxx,
            generator_umask=generator_umask,
        ).encode("utf-8"),
        "tools/install.py": source_installer_contents().encode("utf-8"),
    }
    for relative_path, contents in files.items():
        path = origin / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    run_git(
        origin,
        "add",
        ".gitignore",
        "emscripten-version.txt",
        "bootstrap",
        "emcc.py",
        "em++.py",
        "system/lib/wasmfs/syscalls.cpp",
        "test/fixture.txt",
        "tools/maint/create_entry_points.py",
        "tools/install.py",
    )
    if tracked_entry_point_symlink is not None:
        if tracked_entry_point_symlink_target is None:
            raise ValueError("tracked entry-point symlink target is required")
        output = origin.joinpath(
            *PurePosixPath(tracked_entry_point_symlink).parts
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.symlink_to(tracked_entry_point_symlink_target)
        run_git(origin, "add", "--force", tracked_entry_point_symlink)
    run_git(
        origin,
        "-c",
        "user.name=Chromium Wasm Test",
        "-c",
        "user.email=chromium-wasm-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Add forked Emscripten source",
    )
    return (
        origin,
        run_git(origin, "rev-parse", "HEAD"),
        {**files, "emcc": emcc_contents, "em++": emxx_contents},
    )


def artifact_contents() -> dict[str, bytes]:
    return {
        "clang": b"pinned clang\n",
        "wasm-ld": b"pinned wasm-ld\n",
        "wasm-opt": b"pinned wasm-opt\n",
        "node": b"pinned node\n",
    }


def make_emscripten_pin(
    origin: Path,
    revision: str,
    source_files: dict[str, bytes],
    emsdk: Path,
) -> dict[str, object]:
    artifacts = artifact_contents()
    return {
        "source_remote": str(origin),
        "source_ref": revision,
        "source_revision": revision,
        "source_version": "5.0.6-git",
        "source_file_sha256": {
            "system/lib/wasmfs/syscalls.cpp": hashlib.sha256(
                source_files["system/lib/wasmfs/syscalls.cpp"]
            ).hexdigest(),
        },
        "source_npm_tree_sha256": bootstrap.emscripten_npm_execution_closure_sha256(
            emsdk / "node/test-node_64bit/bin/node"
        ),
        "node_version": "test-node",
        "artifact_sha256": {
            "emcc": hashlib.sha256(source_files["emcc"]).hexdigest(),
            "em++": hashlib.sha256(source_files["em++"]).hexdigest(),
            "emcc.py": hashlib.sha256(source_files["emcc.py"]).hexdigest(),
            "em++.py": hashlib.sha256(source_files["em++.py"]).hexdigest(),
            **{
                name: hashlib.sha256(contents).hexdigest()
                for name, contents in artifacts.items()
            },
        },
    }


def prepare_emsdk(repo_root: Path) -> tuple[Path, Path]:
    emsdk = repo_root / "third_party/emsdk"
    distribution = emsdk / "upstream/emscripten"
    old_files = {
        "emscripten-version.txt": json.dumps("5.0.6").encode("utf-8"),
        "emscripten-revision.txt": b"old-source-revision\n",
        "emcc": b"old emcc\n",
        "em++": b"old em++\n",
        "emcc.py": b"old emcc.py\n",
        "em++.py": b"old em++.py\n",
        "system/lib/wasmfs/syscalls.cpp": b"old fcntl locks\n",
        "old-marker.txt": b"replace only this distribution\n",
    }
    for relative_path, contents in old_files.items():
        path = distribution / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    artifacts = artifact_contents()
    for name in ("clang", "wasm-ld", "wasm-opt"):
        path = emsdk / "upstream/bin" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifacts[name])
    node_root = emsdk / "node/test-node_64bit"
    node_bin = node_root / "bin"
    node_bin.mkdir(parents=True)
    node = node_bin / "node"
    node.write_bytes(artifacts["node"])
    node.chmod(0o755)
    npm_cli = node_root / "lib/node_modules/npm/bin/npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    npm_cli.write_text(npm_cli_contents(), encoding="utf-8")
    npm_cli.chmod(0o755)
    (node_bin / "npm").symlink_to("../lib/node_modules/npm/bin/npm-cli.js")
    (emsdk / ".emscripten").write_text(
        "unchanged configuration\n", encoding="utf-8"
    )
    cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
    cache.mkdir(parents=True)
    (cache / "stale.txt").write_text("stale\n", encoding="utf-8")
    return emsdk, distribution


class EmscriptenSourcePinManifestTest(unittest.TestCase):
    def test_entry_point_outputs_match_pinned_linux_generator(self) -> None:
        self.assertEqual(
            bootstrap.EMSCRIPTEN_SOURCE_ENTRY_POINT_OUTPUTS,
            EXPECTED_ENTRY_POINT_OUTPUTS,
        )

    def test_manifest_pins_default_cxx_launcher(self) -> None:
        emscripten = load_manifest()["emscripten"]
        self.assertIsInstance(emscripten, dict)
        self.assertEqual(
            bootstrap.emscripten_artifact_hash(emscripten, "em++"),
            bootstrap.emscripten_artifact_hash(emscripten, "emcc"),
        )
        self.assertEqual(
            bootstrap.emscripten_artifact_hash(emscripten, "em++.py"),
            "e71423cc294141b49ef763e9d581232315dd5568ae75e595441072861574645b",
        )

    def test_manifest_pins_m7_opfs_source_fork(self) -> None:
        emscripten = load_manifest()["emscripten"]
        self.assertIsInstance(emscripten, dict)
        source_pin = bootstrap.emscripten_source_pin(emscripten)
        self.assertIsNotNone(source_pin)
        assert source_pin is not None
        self.assertEqual(
            source_pin["remote"],
            "https://github.com/Dorbmon/REmscripten.git",
        )
        self.assertEqual(
            source_pin["revision"],
            "c29be46c0c37efd5e58c9e6ef441321a7ee84e98",
        )
        self.assertEqual(source_pin["version"], "5.0.6-git")
        self.assertEqual(
            source_pin["npm_tree_sha256"],
            "a8fa3d3fa1c47360b757c93af09e02fea4932f366367c706dd59b0c5af6dec50",
        )
        self.assertEqual(
            set(source_pin["file_hashes"]), EXPECTED_M7_OPFS_SOURCE_FILES
        )
        self.assertEqual(
            hashlib.sha256(
                json.dumps(
                    source_pin["file_hashes"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            EXPECTED_M7_OPFS_SOURCE_FILE_HASHES_SHA256,
        )

    def test_source_fork_fields_are_strict_and_all_or_none(self) -> None:
        revision = "a" * 40
        complete = {
            "source_remote": "/test/source-origin",
            "source_ref": revision,
            "source_revision": revision,
            "source_version": "5.0.6-git",
            "source_file_sha256": {
                "system/lib/wasmfs/syscalls.cpp": "b" * 64,
            },
            "source_npm_tree_sha256": "c" * 64,
        }
        source_pin = bootstrap.emscripten_source_pin(complete)
        self.assertIsNotNone(source_pin)
        assert source_pin is not None
        self.assertEqual(source_pin["revision"], revision)
        self.assertEqual(source_pin["version"], "5.0.6-git")

        invalid_cases = (
            (
                {"source_revision": revision, "source_remote": "origin"},
                "must be configured together",
            ),
            (
                {
                    key: value
                    for key, value in complete.items()
                    if key != "source_revision"
                },
                "must be configured together",
            ),
            (
                {**complete, "source_ref": "main"},
                "40-character Git hash",
            ),
            (
                {
                    **complete,
                    "source_file_sha256": {"../syscalls.cpp": "b" * 64},
                },
                "canonical POSIX path",
            ),
            ({**complete, "source_magic": "ignored"}, "unknown"),
        )
        for invalid, error in invalid_cases:
            with (
                self.subTest(invalid=invalid, error=error),
                self.assertRaisesRegex(M0Error, error),
            ):
                bootstrap.emscripten_source_pin(invalid)

    def test_source_version_accepts_only_canonical_plain_text_or_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_root = Path(temporary_directory)
            version_path = source_root / "emscripten-version.txt"
            version_path.write_text("5.0.6-git\n", encoding="utf-8")
            self.assertEqual(
                bootstrap.emscripten_source_version(source_root), "5.0.6-git"
            )
            version_path.write_text(json.dumps("5.0.6"), encoding="utf-8")
            self.assertEqual(
                bootstrap.emscripten_source_version(source_root), "5.0.6"
            )
            version_path.write_text("main\n", encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "invalid"):
                bootstrap.emscripten_source_version(source_root)

    def test_release_version_rejects_the_plain_text_fork_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_root = Path(temporary_directory)
            version_path = source_root / "emscripten-version.txt"
            version_path.write_text("5.0.6-git\n", encoding="utf-8")
            with self.assertRaisesRegex(M0Error, "invalid JSON"):
                bootstrap.emscripten_release_version(source_root)
            version_path.write_text(json.dumps("5.0.6"), encoding="utf-8")
            self.assertEqual(
                bootstrap.emscripten_release_version(source_root), "5.0.6"
            )


class EmscriptenSourcePinBootstrapTest(unittest.TestCase):
    def test_installs_verified_plain_text_source_fork_and_invalidates_cache(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            for launcher in ("emcc", "em++"):
                with self.subTest(launcher=launcher):
                    self.assertFalse((origin / launcher).exists())
                    self.assertEqual(
                        run_git(origin, "check-ignore", launcher), launcher
                    )
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            host_bin = repo_root / "host-bin"
            host_bin.mkdir()
            hostile_env_marker = repo_root / "hostile-env-selected.txt"
            hostile_env = host_bin / "env"
            hostile_env.write_text(
                f"#!{sys.executable}\n"
                "import os\n"
                "from pathlib import Path\n"
                "import sys\n"
                "Path(os.environ['HOSTILE_ENV_MARKER']).write_text('bad\\n')\n"
                "os.execv('/usr/bin/env', ['/usr/bin/env', *sys.argv[1:]])\n",
                encoding="utf-8",
            )
            hostile_env.chmod(0o755)
            inherited_path = os.environ.get("PATH", "")
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.dict(
                    os.environ,
                    {
                        "PATH": str(host_bin) + os.pathsep + inherited_path,
                        "HOSTILE_ENV_MARKER": str(hostile_env_marker),
                    },
                ),
            ):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            self.assertEqual(
                (distribution / "emscripten-revision.txt")
                .read_text(encoding="utf-8")
                .strip(),
                revision,
            )
            self.assertEqual(
                (distribution / "emscripten-version.txt").read_text(
                    encoding="utf-8"
                ),
                "5.0.6-git\n",
            )
            self.assertEqual(
                (distribution / "system/lib/wasmfs/syscalls.cpp").read_bytes(),
                source_files["system/lib/wasmfs/syscalls.cpp"],
            )
            for launcher in ("emcc", "em++"):
                with self.subTest(launcher=launcher):
                    path = distribution / launcher
                    self.assertFalse(path.is_symlink())
                    self.assertTrue(path.is_file())
                    self.assertTrue(os.access(path, os.R_OK | os.X_OK))
                    self.assertEqual(path.read_bytes(), source_files[launcher])
                    self.assertEqual(
                        stat.S_IMODE(path.stat().st_mode), 0o755
                    )
            self.assertEqual(
                (distribution / "em++.py").read_bytes(),
                source_files["em++.py"],
            )
            self.assertFalse((distribution / "old-marker.txt").exists())
            self.assertFalse(cache.exists())
            self.assertEqual(
                (emsdk / ".emscripten").read_text(encoding="utf-8"),
                "unchanged configuration\n",
            )
            self.assertEqual(
                (emsdk / "upstream/bin/clang").read_bytes(),
                artifact_contents()["clang"],
            )
            installer_path = (distribution / "installer-path.txt").read_text(
                encoding="utf-8"
            )
            self.assertEqual(
                Path(installer_path).name,
                "installer-tools",
            )
            self.assertNotIn(os.pathsep, installer_path)
            npm_config_paths = (
                distribution / "installer-npm-config.txt"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(npm_config_paths), 2)
            self.assertNotEqual(*npm_config_paths)
            self.assertEqual(Path(npm_config_paths[0]).name, "installer-npmrc")
            self.assertEqual(
                Path(npm_config_paths[1]).name, "installer-npm-globalrc"
            )
            self.assertEqual(
                Path(
                    (distribution / "resolved-npm.txt")
                    .read_text(encoding="utf-8")
                    .strip()
                ).parent.name,
                "installer-tools",
            )
            self.assertEqual(
                (distribution / "npm-ci.txt").read_text(encoding="utf-8"),
                "ok\n",
            )
            self.assertEqual(
                list((emsdk / "upstream").glob(".emscripten-source-pin-*")),
                [],
            )
            self.assertFalse(hostile_env_marker.exists())

    def test_nonexecutable_generated_emxx_is_normalized_before_install(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(
                repo_root, emxx_execute_bits=0
            )
            self.assertFalse((origin / "em++").exists())
            self.assertEqual(run_git(origin, "check-ignore", "em++"), "em++")
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            self.assertEqual(
                (distribution / "em++").read_bytes(), source_files["em++"]
            )
            self.assertEqual(
                stat.S_IMODE((distribution / "em++").stat().st_mode), 0o755
            )

    def test_missing_generated_emxx_preserves_active_distribution_and_cache(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(
                repo_root, generate_emxx=False
            )
            self.assertFalse((origin / "em++").exists())
            self.assertEqual(run_git(origin, "check-ignore", "em++"), "em++")
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(M0Error, "missing em\\+\\+"),
            ):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            self.assertEqual(
                (distribution / "old-marker.txt").read_text(encoding="utf-8"),
                "replace only this distribution\n",
            )
            self.assertTrue((cache / "stale.txt").is_file())
            self.assertEqual(
                list((emsdk / "upstream").glob(".emscripten-source-pin-*")),
                [],
            )

    def test_hostile_umask_normalizes_generated_compiler_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(
                repo_root, generator_umask=0o777
            )
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None

            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            source_launchers = json.loads(
                (distribution / "source-launchers.json").read_text(
                    encoding="utf-8"
                )
            )
            for launcher in ("emcc", "em++"):
                with self.subTest(launcher=launcher):
                    self.assertEqual(
                        source_launchers[launcher],
                        {"mode": 0o755, "readable": True, "executable": True},
                    )
                    path = distribution / launcher
                    self.assertTrue(os.access(path, os.R_OK | os.X_OK))
                    self.assertEqual(path.read_bytes(), source_files[launcher])
                    self.assertEqual(
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                        bootstrap.emscripten_artifact_hash(emscripten, launcher),
                    )
                    self.assertEqual(
                        stat.S_IMODE(path.stat().st_mode), 0o755
                    )

    def test_tracked_entry_point_symlink_is_rejected_before_generation(
        self,
    ) -> None:
        for output_name in ("emcc", "tools/file_packager"):
            with (
                self.subTest(output_name=output_name),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                repo_root = Path(temporary_directory)
                external_marker = repo_root / "external-entry-point-marker"
                external_marker.write_text("unchanged\n", encoding="utf-8")
                origin, revision, source_files = create_source_origin(
                    repo_root,
                    tracked_entry_point_symlink=output_name,
                    tracked_entry_point_symlink_target=external_marker,
                )
                source_output = origin.joinpath(*PurePosixPath(output_name).parts)
                self.assertTrue(source_output.is_symlink())
                self.assertTrue(
                    run_git(origin, "ls-files", "--stage", "--", output_name)
                    .startswith("120000 ")
                )
                emsdk, distribution = prepare_emsdk(repo_root)
                emscripten = make_emscripten_pin(
                    origin, revision, source_files, emsdk
                )
                source_pin = bootstrap.emscripten_source_pin(emscripten)
                assert source_pin is not None
                cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE

                with (
                    mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                    self.assertRaisesRegex(
                        M0Error,
                        "entry-point output is not a regular file: "
                        + output_name,
                    ),
                ):
                    bootstrap.install_emscripten_source_pin(
                        source_pin, emscripten, emsdk, Path(sys.executable)
                    )

                self.assertEqual(
                    external_marker.read_text(encoding="utf-8"), "unchanged\n"
                )
                self.assertEqual(
                    (distribution / "old-marker.txt").read_text(
                        encoding="utf-8"
                    ),
                    "replace only this distribution\n",
                )
                self.assertTrue((cache / "stale.txt").is_file())
                self.assertEqual(
                    list(
                        (emsdk / "upstream").glob(
                            ".emscripten-source-pin-*"
                        )
                    ),
                    [],
                )

    def test_verify_only_detects_tampered_default_cxx_launcher_without_installing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            cache.mkdir(parents=True)
            (cache / "fresh.txt").write_text("retain\n", encoding="utf-8")
            (distribution / "em++").write_text(
                "tampered\n", encoding="utf-8"
            )

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap, "install_emscripten_source_pin"
                ) as install,
                self.assertRaisesRegex(M0Error, "source artifact em\\+\\+"),
            ):
                bootstrap.ensure_emscripten_source_pin(
                    emscripten,
                    emsdk,
                    Path(sys.executable),
                    install=False,
                )

            install.assert_not_called()
            self.assertTrue((cache / "fresh.txt").is_file())

    def test_verify_only_detects_tampered_default_cxx_compiler_module(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            cache.mkdir(parents=True)
            (cache / "fresh.txt").write_text("retain\n", encoding="utf-8")
            (distribution / "em++.py").write_text(
                "tampered\n", encoding="utf-8"
            )

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap, "install_emscripten_source_pin"
                ) as install,
                self.assertRaisesRegex(M0Error, "source artifact em\\+\\+\\.py"),
            ):
                bootstrap.ensure_emscripten_source_pin(
                    emscripten,
                    emsdk,
                    Path(sys.executable),
                    install=False,
                )

            install.assert_not_called()
            self.assertTrue((cache / "fresh.txt").is_file())

    def test_failed_staged_validation_preserves_active_distribution_and_cache(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            emscripten["source_file_sha256"] = {
                "system/lib/wasmfs/syscalls.cpp": "0" * 64,
            }
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(M0Error, "source file"),
            ):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            self.assertEqual(
                (distribution / "old-marker.txt").read_text(encoding="utf-8"),
                "replace only this distribution\n",
            )
            self.assertTrue((cache / "stale.txt").is_file())
            self.assertEqual(
                list((emsdk / "upstream").glob(".emscripten-source-pin-*")),
                [],
            )

    def test_tampered_npm_is_rejected_before_the_source_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            npm_cli = (
                emsdk / "node/test-node_64bit/lib/node_modules/npm/bin/npm-cli.js"
            )
            npm_cli.write_text("tampered npm\n", encoding="utf-8")
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                self.assertRaisesRegex(M0Error, "npm execution closure"),
            ):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            self.assertEqual(
                (distribution / "old-marker.txt").read_text(encoding="utf-8"),
                "replace only this distribution\n",
            )
            self.assertTrue((cache / "stale.txt").is_file())
            self.assertEqual(
                list((emsdk / "upstream").glob(".emscripten-source-pin-*")),
                [],
            )

    def test_nonexecutable_pinned_npm_never_falls_back_to_host_npm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            pinned_npm = (
                emsdk / "node/test-node_64bit/lib/node_modules/npm/bin/npm-cli.js"
            )
            pinned_npm.chmod(0o644)
            host_bin = repo_root / "host-bin"
            host_bin.mkdir()
            host_npm = host_bin / "npm"
            host_npm.write_text(
                f"#!{sys.executable}\n"
                "from pathlib import Path\n"
                "Path.cwd().joinpath('host-npm-selected.txt').write_text('bad\\n')\n",
                encoding="utf-8",
            )
            host_npm.chmod(0o755)
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            inherited_path = os.environ.get("PATH", "")

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.dict(
                    os.environ,
                    {"PATH": str(host_bin) + os.pathsep + inherited_path},
                ),
                self.assertRaisesRegex(M0Error, "npm launcher is not executable"),
            ):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            self.assertFalse((distribution / "host-npm-selected.txt").exists())
            self.assertEqual(
                (distribution / "old-marker.txt").read_text(encoding="utf-8"),
                "replace only this distribution\n",
            )
            self.assertTrue((cache / "stale.txt").is_file())

    def test_npm_closure_rejects_an_escaping_symlinked_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            emsdk, _distribution = prepare_emsdk(repo_root)
            node_root = emsdk / "node/test-node_64bit"
            lib_directory = node_root / "lib"
            external_lib = repo_root / "external-lib"
            lib_directory.rename(external_lib)
            lib_directory.symlink_to(external_lib, target_is_directory=True)

            with self.assertRaisesRegex(M0Error, "lib directory is invalid"):
                bootstrap.emscripten_npm_execution_closure_sha256(
                    node_root / "bin/node"
                )

    def test_failed_promotion_restores_active_distribution_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            original_replace = os.replace

            def replace(source: object, destination: object) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    destination_path == distribution
                    and source_path.name == "distribution"
                ):
                    raise OSError("forced candidate promotion failure")
                original_replace(source, destination)

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(bootstrap.os, "replace", side_effect=replace),
                self.assertRaisesRegex(
                    M0Error, "previous distribution and cache were restored"
                ),
            ):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            self.assertEqual(
                (distribution / "old-marker.txt").read_text(encoding="utf-8"),
                "replace only this distribution\n",
            )
            self.assertTrue((cache / "stale.txt").is_file())
            self.assertEqual(
                list((emsdk / "upstream").glob(".emscripten-source-pin-*")),
                [],
            )

    def test_failed_rollback_preserves_the_recoverable_sdk_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            original_replace = os.replace

            def replace(source: object, destination: object) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                if destination_path == distribution and source_path.name in {
                    "distribution",
                    "previous-distribution",
                }:
                    raise OSError("forced promotion or rollback failure")
                original_replace(source, destination)

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(bootstrap.os, "replace", side_effect=replace),
                self.assertRaisesRegex(M0Error, "recovery copies were preserved"),
            ):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )

            recovery_roots = list(
                (emsdk / "upstream").glob(".emscripten-source-pin-*")
            )
            self.assertEqual(len(recovery_roots), 1)
            self.assertEqual(
                (
                    recovery_roots[0]
                    / "previous-distribution/old-marker.txt"
                ).read_text(encoding="utf-8"),
                "replace only this distribution\n",
            )
            self.assertTrue((cache / "stale.txt").is_file())

    def test_verify_only_detects_tampering_without_installing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory)
            origin, revision, source_files = create_source_origin(repo_root)
            emsdk, distribution = prepare_emsdk(repo_root)
            emscripten = make_emscripten_pin(
                origin, revision, source_files, emsdk
            )
            source_pin = bootstrap.emscripten_source_pin(emscripten)
            assert source_pin is not None
            with mock.patch.object(bootstrap, "REPO_ROOT", repo_root):
                bootstrap.install_emscripten_source_pin(
                    source_pin, emscripten, emsdk, Path(sys.executable)
                )
            cache = repo_root / bootstrap.EMSCRIPTEN_SOURCE_CACHE
            cache.mkdir(parents=True)
            (cache / "fresh.txt").write_text("retain\n", encoding="utf-8")
            (distribution / "system/lib/wasmfs/syscalls.cpp").write_text(
                "tampered\n", encoding="utf-8"
            )

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", repo_root),
                mock.patch.object(
                    bootstrap, "install_emscripten_source_pin"
                ) as install,
                self.assertRaisesRegex(M0Error, "source file"),
            ):
                bootstrap.ensure_emscripten_source_pin(
                    emscripten,
                    emsdk,
                    Path(sys.executable),
                    install=False,
                )

            install.assert_not_called()
            self.assertTrue((cache / "fresh.txt").is_file())

    def test_promotion_rolls_back_when_candidate_rename_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_root = root / "staging"
            staging_root.mkdir()
            candidate = staging_root / "distribution"
            candidate.mkdir()
            (candidate / "marker").write_text("candidate\n", encoding="utf-8")
            active = root / "emscripten"
            active.mkdir()
            (active / "marker").write_text("active\n", encoding="utf-8")
            cache = root / "cache"
            cache.mkdir()
            (cache / "marker").write_text("cache\n", encoding="utf-8")
            original_replace = os.replace

            def replace(source: object, destination: object) -> None:
                if Path(source) == candidate and Path(destination) == active:
                    raise OSError("forced promotion failure")
                original_replace(source, destination)

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", root),
                mock.patch.object(bootstrap.os, "replace", side_effect=replace),
                self.assertRaisesRegex(
                    M0Error, "previous distribution and cache were restored"
                ),
            ):
                bootstrap.promote_emscripten_source_distribution(
                    candidate, active, staging_root, cache
                )

            self.assertEqual(
                (active / "marker").read_text(encoding="utf-8"), "active\n"
            )
            self.assertTrue((candidate / "marker").is_file())
            self.assertEqual(
                (cache / "marker").read_text(encoding="utf-8"), "cache\n"
            )

    def test_interrupted_promotion_restores_source_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_root = root / "staging"
            staging_root.mkdir()
            candidate = staging_root / "distribution"
            candidate.mkdir()
            (candidate / "marker").write_text("candidate\n", encoding="utf-8")
            active = root / "emscripten"
            active.mkdir()
            (active / "marker").write_text("active\n", encoding="utf-8")
            cache = root / "cache"
            cache.mkdir()
            (cache / "marker").write_text("cache\n", encoding="utf-8")
            original_replace = os.replace

            def replace(source: object, destination: object) -> None:
                if Path(source) == candidate and Path(destination) == active:
                    raise KeyboardInterrupt()
                original_replace(source, destination)

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", root),
                mock.patch.object(bootstrap.os, "replace", side_effect=replace),
                self.assertRaises(KeyboardInterrupt),
            ):
                bootstrap.promote_emscripten_source_distribution(
                    candidate, active, staging_root, cache
                )

            self.assertEqual(
                (active / "marker").read_text(encoding="utf-8"), "active\n"
            )
            self.assertEqual(
                (cache / "marker").read_text(encoding="utf-8"), "cache\n"
            )
            self.assertFalse(
                bootstrap.has_emscripten_source_recovery_copy(staging_root)
            )

    def test_interrupt_after_cache_move_restores_source_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_root = root / "staging"
            staging_root.mkdir()
            candidate = staging_root / "distribution"
            candidate.mkdir()
            (candidate / "marker").write_text("candidate\n", encoding="utf-8")
            active = root / "emscripten"
            active.mkdir()
            (active / "marker").write_text("active\n", encoding="utf-8")
            cache = root / "cache"
            cache.mkdir()
            (cache / "marker").write_text("cache\n", encoding="utf-8")
            cache_backup = staging_root / "previous-cache"
            original_replace = os.replace

            def replace(source: object, destination: object) -> None:
                original_replace(source, destination)
                if Path(source) == cache and Path(destination) == cache_backup:
                    raise KeyboardInterrupt()

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", root),
                mock.patch.object(bootstrap.os, "replace", side_effect=replace),
                self.assertRaises(KeyboardInterrupt),
            ):
                bootstrap.promote_emscripten_source_distribution(
                    candidate, active, staging_root, cache
                )

            self.assertEqual(
                (active / "marker").read_text(encoding="utf-8"), "active\n"
            )
            self.assertEqual(
                (cache / "marker").read_text(encoding="utf-8"), "cache\n"
            )
            self.assertFalse(
                bootstrap.has_emscripten_source_recovery_copy(staging_root)
            )

    def test_interrupt_after_candidate_promotion_preserves_old_cache_backup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging_root = root / "staging"
            staging_root.mkdir()
            candidate = staging_root / "distribution"
            candidate.mkdir()
            (candidate / "marker").write_text("candidate\n", encoding="utf-8")
            active = root / "emscripten"
            active.mkdir()
            (active / "marker").write_text("active\n", encoding="utf-8")
            cache = root / "cache"
            cache.mkdir()
            (cache / "marker").write_text("cache\n", encoding="utf-8")
            original_replace = os.replace

            def replace(source: object, destination: object) -> None:
                original_replace(source, destination)
                if Path(source) == candidate and Path(destination) == active:
                    raise KeyboardInterrupt()

            with (
                mock.patch.object(bootstrap, "REPO_ROOT", root),
                mock.patch.object(bootstrap.os, "replace", side_effect=replace),
                self.assertRaisesRegex(M0Error, "recovery copies were preserved"),
            ):
                bootstrap.promote_emscripten_source_distribution(
                    candidate, active, staging_root, cache
                )

            self.assertEqual(
                (active / "marker").read_text(encoding="utf-8"), "candidate\n"
            )
            self.assertFalse(cache.exists())
            self.assertEqual(
                (staging_root / "previous-distribution/marker")
                .read_text(encoding="utf-8"),
                "active\n",
            )
            self.assertEqual(
                (staging_root / "previous-cache/marker").read_text(
                    encoding="utf-8"
                ),
                "cache\n",
            )


if __name__ == "__main__":
    unittest.main()

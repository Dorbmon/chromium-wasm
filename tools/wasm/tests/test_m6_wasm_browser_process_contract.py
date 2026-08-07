# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Source contracts for the source-selected M6 Wasm BrowserProcess."""

from pathlib import Path
import re
import unittest


_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (_ROOT / relative_path).read_text(encoding="utf-8")


def _source_set_body(build_file: str, target: str) -> str:
    match = re.search(
        rf'\bsource_set\s*\(\s*"{re.escape(target)}"\s*\)', build_file
    )
    if not match:
        raise AssertionError(f"could not find source set {target!r}")

    opening_brace = build_file.find("{", match.end())
    if opening_brace == -1:
        raise AssertionError(f"source set {target!r} has no opening brace")

    depth = 0
    for index in range(opening_brace, len(build_file)):
        if build_file[index] == "{":
            depth += 1
        elif build_file[index] == "}":
            depth -= 1
            if depth == 0:
                return build_file[opening_brace + 1 : index]
    raise AssertionError(f"source set {target!r} has no closing brace")


class WasmBrowserProcessContractTest(unittest.TestCase):
    def test_wasm_process_owns_only_real_m6_process_state(self) -> None:
        header = _read("chrome/browser/wasm/wasm_browser_process.h")
        source = _read("chrome/browser/wasm/wasm_browser_process.cc")

        self.assertIn(
            "class WasmBrowserProcess final : public BrowserProcess", header
        )
        self.assertNotIn(
            '#include "chrome/browser/browser_process_impl.h"', header
        )
        self.assertNotIn(
            '#include "chrome/test/base/testing_browser_process.h"', header
        )
        self.assertIn("ui::UnownedUserDataHost unowned_user_data_host_", header)
        self.assertIn("std::unique_ptr<PrefService> local_state_", header)
        self.assertIn("SEQUENCE_CHECKER(sequence_checker_)", header)
        self.assertIn("raw_ptr<ProfileManager> profile_manager_", header)

        self.assertIn("CreateInMemoryLocalState", source)
        self.assertIn("base::MakeRefCounted<PrefRegistrySimple>()", source)
        self.assertIn("base::MakeRefCounted<InMemoryPrefStore>()", source)
        self.assertIn("DeviceParentalControlsNoOpImpl", source)
        self.assertIn("CHECK(!g_browser_process)", source)
        self.assertIn("g_browser_process = this", source)
        self.assertIn("CHECK_EQ(g_browser_process, this)", source)
        self.assertIn("g_browser_process = nullptr", source)
        self.assertIn("DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_)", source)

    def test_future_profile_and_network_services_are_explicit_injection_points(
        self,
    ) -> None:
        header = _read("chrome/browser/wasm/wasm_browser_process.h")
        source = _read("chrome/browser/wasm/wasm_browser_process.cc")

        for method in (
            "SetProfileManager(ProfileManager* profile_manager)",
            "SetSystemNetworkContextManager(",
            "SetSharedURLLoaderFactory(",
            "SetNetworkQualityTracker(",
        ):
            self.assertIn(method, header)

        self.assertIn("LogUnavailableService", source)
        self.assertIn("FailUnavailableService", source)
        self.assertIn("Do not add a successful-looking stub", source)
        self.assertIn("OPFS-backed implementation", header)
        self.assertIn("key_provider_interface", _read("chrome/browser/wasm/BUILD.gn"))

    def test_unmarked_services_fail_instead_of_returning_null(self) -> None:
        source = _read("chrome/browser/wasm/wasm_browser_process.cc")

        self.assertIn(
            "[[noreturn]] void WasmBrowserProcess::FailUnavailableService",
            source,
        )
        for service in (
            "metrics services manager",
            "Chrome origin-trial settings storage",
            "OS cryptographic key store",
            "desktop build-state service",
            "Chrome global features before Wasm initialization",
        ):
            self.assertIn(f'FailUnavailableService("{service}")', source)

        # Null is reserved for BrowserProcess's documented nullable service
        # group, StatusTray/GetTabManager, and pre-injection accessors.
        self.assertNotIn(
            "GetFeatures() {\n  LogUnavailableService", source
        )
        self.assertNotIn(
            "os_crypt_async() {\n  LogUnavailableService", source
        )

    def test_m6_excludes_desktop_system_tray_hooks_from_the_interface(self) -> None:
        browser_process = _read("chrome/browser/browser_process.h")
        browser_process_impl_header = _read(
            "chrome/browser/browser_process_impl.h"
        )
        browser_process_impl_source = _read(
            "chrome/browser/browser_process_impl.cc"
        )
        testing_process_header = _read("chrome/test/base/testing_browser_process.h")
        testing_process_source = _read("chrome/test/base/testing_browser_process.cc")
        wasm_header = _read("chrome/browser/wasm/wasm_browser_process.h")
        wasm_source = _read("chrome/browser/wasm/wasm_browser_process.cc")

        boundary = "#if !BUILDFLAG(IS_ANDROID) && !BUILDFLAG(IS_WASM)"
        for text in (
            browser_process,
            browser_process_impl_header,
            browser_process_impl_source,
            testing_process_header,
            testing_process_source,
        ):
            self.assertIn(boundary, text)

        self.assertIn("no native status-tray surface", browser_process)
        self.assertNotIn("HidSystemTrayIcon", wasm_header)
        self.assertNotIn("UsbSystemTrayIcon", wasm_header)
        self.assertNotIn("HidSystemTrayIcon", wasm_source)
        self.assertNotIn("UsbSystemTrayIcon", wasm_source)

    def test_unowned_user_data_is_source_selected_only_for_m6_chrome(self) -> None:
        build = _read("ui/base/unowned_user_data/BUILD.gn")

        self.assertIn("(is_wasm && enable_chromium_wasm_chrome)", build)
        self.assertIn("M6 source-selected Chrome target", build)

    def test_process_owns_real_global_browser_collection_without_global_features(
        self,
    ) -> None:
        build = _read("chrome/browser/wasm/BUILD.gn")
        process_header = _read("chrome/browser/wasm/wasm_browser_process.h")
        process_source = _read("chrome/browser/wasm/wasm_browser_process.cc")
        collection_header = _read(
            "chrome/browser/wasm/wasm_global_browser_collection.h"
        )
        collection_source = _read(
            "chrome/browser/wasm/wasm_global_browser_collection.cc"
        )
        desktop_collection_source = _read(
            "chrome/browser/ui/browser_window/internal/global_browser_collection.cc"
        )

        collection_target = _source_set_body(build, "wasm_browser_collection")
        process_target = _source_set_body(build, "wasm_browser_process")
        for source_file in (
            "../ui/browser_window/internal/browser_collection.cc",
            "../ui/browser_window/internal/"
            "global_browser_collection_platform_delegate_non_android.cc",
            "wasm_global_browser_collection.cc",
            "wasm_global_browser_collection.h",
        ):
            with self.subTest(source_file=source_file):
                self.assertIn(f'"{source_file}"', collection_target)

        self.assertIn('":wasm_browser_collection",', process_target)
        public_deps_match = re.search(
            r"\bpublic_deps\s*=\s*\[(.*?)\]", collection_target, re.DOTALL
        )
        self.assertIsNotNone(public_deps_match)
        self.assertIn(
            '"//chrome/browser/ui/browser_window"', public_deps_match.group(1)
        )
        for forbidden_target in (
            "//chrome/browser:global_features",
            "//chrome/browser/ui/browser_window/internal",
        ):
            with self.subTest(forbidden_target=forbidden_target):
                self.assertNotIn(f'"{forbidden_target}"', collection_target)

        # Keep the generic desktop source unchanged. The Wasm executable owns
        # a source-selected implementation because the desktop accessor reaches
        # GlobalFeatures, whose service graph is intentionally absent here.
        self.assertIn(
            "g_browser_process->GetFeatures()->global_browser_collection()",
            desktop_collection_source,
        )
        self.assertNotIn("global_features.h", collection_source)
        self.assertIn("GlobalBrowserCollection::GetInstance", collection_source)
        self.assertIn(
            "return GetWasmGlobalBrowserCollection();", collection_source
        )
        for registration_api in (
            "RegisterWasmGlobalBrowserCollection",
            "UnregisterWasmGlobalBrowserCollection",
            "GetWasmGlobalBrowserCollection",
        ):
            with self.subTest(registration_api=registration_api):
                self.assertIn(registration_api, collection_header)
                self.assertIn(registration_api, collection_source)

        self.assertIn(
            "std::unique_ptr<GlobalBrowserCollection> global_browser_collection_",
            process_header,
        )
        self.assertIn(
            "global_browser_collection_ = std::make_unique<GlobalBrowserCollection>()",
            process_source,
        )
        self.assertIn(
            "RegisterWasmGlobalBrowserCollection(global_browser_collection_.get())",
            process_source,
        )
        self.assertIn("CHECK(global_browser_collection_->IsEmpty())", process_source)
        self.assertIn(
            "UnregisterWasmGlobalBrowserCollection(global_browser_collection_.get())",
            process_source,
        )
        destructor = process_source.split("WasmBrowserProcess::~WasmBrowserProcess()", 1)[
            1
        ].split("void WasmBrowserProcess::SetProfileManager", 1)[0]
        self.assertLess(
            destructor.index("UnregisterWasmGlobalBrowserCollection"),
            destructor.index("global_browser_collection_.reset()"),
        )
        self.assertIn(
            'FailUnavailableService("Chrome global features before Wasm initialization")',
            process_source,
        )


if __name__ == "__main__":
    unittest.main()

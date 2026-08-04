#!/usr/bin/env python3
"""Focused source contracts for the M5 WISP-only hostname path."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[3]


def source(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


class M5WispDnsSourceContractTest(unittest.TestCase):
    def test_wasm_cannot_select_chromium_builtin_dns(self) -> None:
        expected = "enable_built_in_dns = use_blink && !is_wasm"
        self.assertIn(expected, source("net/BUILD.gn"))
        self.assertIn(expected, source("net/dns/BUILD.gn"))

        manager = source("net/dns/host_resolver_manager.cc")
        self.assertIn("#if BUILDFLAG(IS_WASM)", manager)
        self.assertIn("HostResolverSource::LOCAL_ONLY", manager)
        self.assertIn("HostResolverSource::DNS && !ip_address.IsValid()", manager)
        self.assertIn("HostResolverSource::MULTICAST_DNS", manager)
        self.assertIn("ResemblesMulticastDNSName", manager)
        self.assertIn("out_tasks->push_back(TaskType::SYSTEM);", manager)
        self.assertIn("Do not consult Chromium", manager)
        self.assertIn("if (resolved) {", manager)
        self.assertIn("return HostCache::Entry(ERR_NAME_NOT_RESOLVED", manager)
        self.assertIn("ERR_NOT_IMPLEMENTED", manager)
        self.assertIn("WISP owns destination address-family selection", manager)

    def test_network_service_owns_the_wisp_system_resolver_lifetime(self) -> None:
        service = source("services/network/network_service.cc")

        self.assertIn("net::InstallWasmWispSystemDnsResolver();", service)
        self.assertIn("net::ResetWasmWispDestinationRegistry();", service)
        self.assertIn("Ignoring unsupported system DNS resolver on Wasm", service)
        self.assertIn("Ignoring unsupported Chromium stub DNS configuration", service)
        self.assertIn("System DNS resolver overrides are unsupported on Wasm", service)

    def test_registry_is_bounded_async_and_recovers_the_hostname(self) -> None:
        resolver = source("net/dns/wisp_host_resolver_wasm.cc")
        resolver_header = source("net/dns/wisp_host_resolver_wasm.h")
        tcp_socket = source("net/socket/tcp_socket_wasm.cc")

        self.assertIn("kMaximumWispDestinations = 16384", resolver)
        self.assertIn("ERR_INSUFFICIENT_RESOURCES", resolver)
        self.assertIn("HOST_RESOLVER_LOOPBACK_ONLY", resolver)
        self.assertIn("GetCurrentDefault()->PostTask", resolver)
        self.assertIn("MakeOpaquePublicIPv4Address", resolver)
        self.assertIn("IsPubliclyRoutable()", resolver)
        self.assertIn("mutable base::Lock lock_", resolver)
        self.assertIn("InstallWasmWispSystemDnsResolver", resolver_header)
        self.assertIn("GetWasmWispDestinationHostname", resolver_header)
        self.assertNotIn("getaddrinfo", resolver)
        self.assertNotIn("fetch(", resolver)

        self.assertIn('"net/dns/wisp_host_resolver_wasm.h"', tcp_socket)
        self.assertIn("GetWasmWispDestinationHostname(address.address())", tcp_socket)
        self.assertIn("OpenWasmWispStream(stream_id_, hostname", tcp_socket)
        self.assertIn("IsPubliclyRoutable()", tcp_socket)
        self.assertIn("IsMulticast()", tcp_socket)
        self.assertIn("ERR_ADDRESS_UNREACHABLE", tcp_socket)

    def test_stub_dns_configuration_is_disabled_at_its_callers(self) -> None:
        shell = source("content/shell/browser/shell_content_browser_client.cc")
        chrome = source("chrome/browser/net/stub_resolver_config_reader.cc")

        self.assertIn("!BUILDFLAG(IS_ANDROID) && !BUILDFLAG(IS_WASM)", shell)
        self.assertIn("#if BUILDFLAG(IS_WASM)", chrome)
        self.assertIn("return false;", chrome)
        self.assertIn("#if !BUILDFLAG(IS_WASM)", chrome)

    def test_wasm_forces_tcp_only_and_rejects_webtransport(self) -> None:
        service = source("services/network/network_service.cc")
        context = source("services/network/network_context.cc")

        self.assertIn("WISP supplies TCP streams only", service)
        self.assertIn("quic_disabled_ = true;", service)
        self.assertIn("if (quic_disabled_) {", service)
        self.assertIn("network_context->DisableQuic();", service)

        self.assertIn("Standalone WebTransport creates a dedicated HTTP/3", context)
        self.assertIn("net::WebTransportError(net::ERR_NOT_IMPLEMENTED)", context)
        self.assertIn("handshake_client->OnHandshakeFailed", context)
        self.assertIn("#if BUILDFLAG(IS_WASM)", context)
        self.assertIn("Ignoring hostname mapping switches on Wasm", context)
        self.assertIn("Rejecting unsupported custom DNS configuration on Wasm", context)
        self.assertIn("mDNS responders are unsupported on Wasm", context)

        host_resolver = source("services/network/host_resolver.cc")
        self.assertIn("std::move(callback).Run(net::ERR_NOT_IMPLEMENTED);", host_resolver)


if __name__ == "__main__":
    unittest.main()

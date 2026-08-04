// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/dns/wisp_host_resolver_wasm.h"

#include <stdint.h>

#include <map>
#include <optional>
#include <string>
#include <utility>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/no_destructor.h"
#include "base/rand_util.h"
#include "base/synchronization/lock.h"
#include "base/task/sequenced_task_runner.h"
#include "base/thread_annotations.h"
#include "build/build_config.h"
#include "net/base/address_family.h"
#include "net/base/address_list.h"
#include "net/base/ip_address.h"
#include "net/base/ip_endpoint.h"
#include "net/base/net_errors.h"
#include "net/dns/host_resolver_system_task.h"

#if !BUILDFLAG(IS_WASM)
#error "wisp_host_resolver_wasm.cc must only be built for WebAssembly"
#endif

namespace net {

namespace {

// Keep this below the smallest synthetic address space and, more importantly,
// bounded independently from the HostResolver cache. An entry remains stable
// for the Network Service lifetime because cached IPEndPoints may outlive a
// single socket attempt.
constexpr size_t kMaximumWispDestinations = 16384;
constexpr size_t kMaximumMarkerGenerationAttempts = 128;

uint8_t ByteAt(uint64_t value, int shift) {
  return static_cast<uint8_t>((value >> shift) & 0xffu);
}

IPAddress MakeOpaquePublicIPv4Address() {
  const uint32_t value = static_cast<uint32_t>(base::RandUint64());
  return IPAddress(static_cast<uint8_t>(value >> 24),
                   static_cast<uint8_t>(value >> 16),
                   static_cast<uint8_t>(value >> 8),
                   static_cast<uint8_t>(value));
}

IPAddress MakeOpaquePublicIPv6Address() {
  const uint64_t upper = base::RandUint64();
  const uint64_t lower = base::RandUint64();
  // Force the first three bits to 001, the IPv6 global-unicast range. The
  // rest stays opaque and random, making a collision with an
  // application-provided IP literal unlikely.
  return IPAddress(static_cast<uint8_t>(0x20 | (upper >> 56 & 0x1fu)),
                   ByteAt(upper, 48), ByteAt(upper, 40), ByteAt(upper, 32),
                   ByteAt(upper, 24), ByteAt(upper, 16), ByteAt(upper, 8),
                   ByteAt(upper, 0), ByteAt(lower, 56), ByteAt(lower, 48),
                   ByteAt(lower, 40), ByteAt(lower, 32), ByteAt(lower, 24),
                   ByteAt(lower, 16), ByteAt(lower, 8), ByteAt(lower, 0));
}

class WispDestinationRegistry {
 public:
  WispDestinationRegistry() = default;
  WispDestinationRegistry(const WispDestinationRegistry&) = delete;
  WispDestinationRegistry& operator=(const WispDestinationRegistry&) = delete;
  ~WispDestinationRegistry() = default;

  std::optional<IPAddress> GetOrCreate(std::string hostname,
                                        AddressFamily address_family) {
    base::AutoLock lock(lock_);

    auto existing = destinations_by_hostname_.find(hostname);
    if (existing == destinations_by_hostname_.end()) {
      if (destinations_by_hostname_.size() >= kMaximumWispDestinations) {
        return std::nullopt;
      }

      const std::optional<Destination> destination = MakeDestination();
      if (!destination.has_value()) {
        return std::nullopt;
      }
      auto [inserted, did_insert] = destinations_by_hostname_.emplace(
          std::move(hostname), std::move(*destination));
      CHECK(did_insert);
      CHECK(address_to_hostname_
                .emplace(inserted->second.ipv4, inserted->first)
                .second);
      CHECK(address_to_hostname_
                .emplace(inserted->second.ipv6, inserted->first)
                .second);
      existing = inserted;
    }

    switch (address_family) {
      case ADDRESS_FAMILY_IPV6:
        return existing->second.ipv6;
      case ADDRESS_FAMILY_UNSPECIFIED:
      case ADDRESS_FAMILY_IPV4:
        // A WISP TCP stream is independent of the page's host-network address
        // family. Returning only IPv4 for unspecified requests avoids a
        // duplicate Happy-Eyeballs stream for one proxy-side hostname connect.
        return existing->second.ipv4;
    }
    return std::nullopt;
  }

  std::optional<std::string> Lookup(const IPAddress& address) const {
    base::AutoLock lock(lock_);
    auto found = address_to_hostname_.find(address);
    if (found == address_to_hostname_.end()) {
      return std::nullopt;
    }
    return found->second;
  }

  void Reset() {
    base::AutoLock lock(lock_);
    destinations_by_hostname_.clear();
    address_to_hostname_.clear();
  }

 private:
  struct Destination {
    IPAddress ipv4;
    IPAddress ipv6;
  };

  std::optional<Destination> MakeDestination()
      EXCLUSIVE_LOCKS_REQUIRED(lock_) {
    for (size_t attempt = 0; attempt < kMaximumMarkerGenerationAttempts;
         ++attempt) {
      Destination destination{MakeOpaquePublicIPv4Address(),
                              MakeOpaquePublicIPv6Address()};
      // These opaque markers remain visible to generic Chromium checks before
      // TCPSocketWasm recovers the hostname. They must therefore look public
      // to both Private Network Access and generic socket validation.
      if (!destination.ipv4.IsPubliclyRoutable() ||
          !destination.ipv6.IsPubliclyRoutable()) {
        continue;
      }
      if (address_to_hostname_.find(destination.ipv4) !=
              address_to_hostname_.end() ||
          address_to_hostname_.find(destination.ipv6) !=
              address_to_hostname_.end()) {
        continue;
      }
      return destination;
    }
    return std::nullopt;
  }

  mutable base::Lock lock_;
  std::map<std::string, Destination> destinations_by_hostname_
      GUARDED_BY(lock_);
  std::map<IPAddress, std::string> address_to_hostname_ GUARDED_BY(lock_);
};

WispDestinationRegistry& GetWispDestinationRegistry() {
  static base::NoDestructor<WispDestinationRegistry> registry;
  return *registry;
}

void PostResolverResult(SystemDnsResultsCallback results_callback,
                        AddressList addresses,
                        int net_error) {
  // HostResolverSystemTask requires this callback to be asynchronous: it may
  // own and destroy the task that invoked the override.
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          [](SystemDnsResultsCallback callback, AddressList result_addresses,
             int result_error) {
            std::move(callback).Run(result_addresses, /*os_error=*/0,
                                    result_error);
          },
          std::move(results_callback), std::move(addresses), net_error));
}

void ResolveWasmWispDestination(
    const std::optional<std::string>& hostname,
    AddressFamily address_family,
    HostResolverFlags host_resolver_flags,
    SystemDnsResultsCallback results_callback,
    handles::NetworkHandle) {
  // A system-hostname lookup cannot be represented as a WISP CONNECT
  // destination. Likewise, returning a virtual public address for a request
  // explicitly restricted to loopback would violate the caller's contract.
  if (!hostname.has_value() || hostname->empty() ||
      (host_resolver_flags & HOST_RESOLVER_LOOPBACK_ONLY)) {
    PostResolverResult(std::move(results_callback), AddressList(),
                       ERR_NAME_NOT_RESOLVED);
    return;
  }

  const std::optional<IPAddress> address =
      GetWispDestinationRegistry().GetOrCreate(*hostname, address_family);
  if (!address.has_value()) {
    PostResolverResult(std::move(results_callback), AddressList(),
                       ERR_INSUFFICIENT_RESOURCES);
    return;
  }

  PostResolverResult(std::move(results_callback),
                     AddressList(IPEndPoint(*address, /*port=*/0)), OK);
}

}  // namespace

void InstallWasmWispSystemDnsResolver() {
  SetSystemDnsResolverOverride(
      base::BindRepeating(&ResolveWasmWispDestination));
}

void ResetWasmWispDestinationRegistry() {
  GetWispDestinationRegistry().Reset();
}

std::optional<std::string> GetWasmWispDestinationHostname(
    const IPAddress& address) {
  return GetWispDestinationRegistry().Lookup(address);
}

}  // namespace net

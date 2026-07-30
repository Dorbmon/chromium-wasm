// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/dns/address_sorter.h"

#include <cstdint>
#include <memory>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/functional/bind.h"
#include "base/test/task_environment.h"
#include "net/base/ip_address.h"
#include "net/base/ip_endpoint.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace net {

namespace {

IPEndPoint MakeEndpoint(const char* address, uint16_t port) {
  IPAddress ip_address;
  CHECK(ip_address.AssignFromIPLiteral(address));
  return IPEndPoint(ip_address, port);
}

TEST(AddressSorterWasmTest, PreservesResolverOrderAsynchronously) {
  base::test::TaskEnvironment task_environment;
  auto sorter = AddressSorter::CreateAddressSorter();
  const std::vector<IPEndPoint> endpoints = {
      MakeEndpoint("10.0.0.1", 443),
      MakeEndpoint("2001:4860:4860::8888", 8443),
      MakeEndpoint("::1", 80),
  };
  bool callback_called = false;
  bool success = false;
  std::vector<IPEndPoint> sorted;

  sorter->Sort(
      endpoints,
      base::BindOnce(
          [](bool* callback_called, bool* success,
             std::vector<IPEndPoint>* sorted, bool callback_success,
             std::vector<IPEndPoint> callback_sorted) {
            *callback_called = true;
            *success = callback_success;
            *sorted = std::move(callback_sorted);
          },
          &callback_called, &success, &sorted));

  EXPECT_FALSE(callback_called);
  task_environment.RunUntilIdle();
  EXPECT_TRUE(callback_called);
  EXPECT_TRUE(success);
  EXPECT_EQ(endpoints, sorted);
}

TEST(AddressSorterWasmTest, CompletionOutlivesSorter) {
  base::test::TaskEnvironment task_environment;
  auto sorter = AddressSorter::CreateAddressSorter();
  const std::vector<IPEndPoint> endpoints = {
      MakeEndpoint("192.0.2.1", 443),
      MakeEndpoint("2001:db8::1", 443),
  };
  bool callback_called = false;

  sorter->Sort(
      endpoints,
      base::BindOnce(
          [](bool* callback_called, bool success,
             std::vector<IPEndPoint> sorted) {
            *callback_called = true;
            EXPECT_TRUE(success);
            EXPECT_FALSE(sorted.empty());
          },
          &callback_called));
  sorter.reset();

  EXPECT_FALSE(callback_called);
  task_environment.RunUntilIdle();
  EXPECT_TRUE(callback_called);
}

}  // namespace

}  // namespace net

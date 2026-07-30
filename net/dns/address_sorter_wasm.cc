// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "net/dns/address_sorter.h"

#include <memory>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/location.h"
#include "base/task/sequenced_task_runner.h"
#include "net/base/ip_endpoint.h"

namespace net {

namespace {

class AddressSorterWasm final : public AddressSorter {
 public:
  AddressSorterWasm() = default;
  ~AddressSorterWasm() override = default;

  AddressSorterWasm(const AddressSorterWasm&) = delete;
  AddressSorterWasm& operator=(const AddressSorterWasm&) = delete;

  void Sort(const std::vector<IPEndPoint>& endpoints,
            CallbackType callback) const override {
    // Wasm has no native source-address or interface policy provider. Preserve
    // the resolver's order until the WISP transport can provide equivalent
    // reachability data. Completing asynchronously keeps the caller sequence
    // unblocked and lets the posted closure outlive this sorter safely.
    base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE,
        base::BindOnce(&AddressSorterWasm::CompleteSort, std::move(callback),
                       endpoints));
  }

 private:
  static void CompleteSort(CallbackType callback,
                           std::vector<IPEndPoint> endpoints) {
    // Success describes the ordering operation, not network reachability.
    std::move(callback).Run(/*success=*/true, std::move(endpoints));
  }
};

}  // namespace

// static
std::unique_ptr<AddressSorter> AddressSorter::CreateAddressSorter() {
  return std::make_unique<AddressSorterWasm>();
}

}  // namespace net

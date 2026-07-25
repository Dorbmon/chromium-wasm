// Copyright 2018 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "mojo/public/cpp/base/file_mojom_traits.h"

#include "base/files/file.h"
#include "build/build_config.h"

namespace mojo {

mojo::PlatformHandle
StructTraits<mojo_base::mojom::FileDataView, base::File>::fd(base::File& file) {
  DCHECK(file.IsValid());

#if BUILDFLAG(IS_WASM)
  CHECK(false) << "Mojo platform file transport is unsupported on Wasm";
#else
  return mojo::PlatformHandle(
      base::ScopedPlatformFile(file.TakePlatformFile()));
#endif
}

bool StructTraits<mojo_base::mojom::FileDataView, base::File>::Read(
    mojo_base::mojom::FileDataView data,
    base::File* file) {
#if BUILDFLAG(IS_WASM)
  return false;
#else
  *file = base::File(data.TakeFd().TakePlatformFile(), data.async());
  return true;
#endif
}

}  // namespace mojo

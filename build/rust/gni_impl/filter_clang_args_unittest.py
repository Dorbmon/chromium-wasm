#!/usr/bin/env python3
# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from filter_clang_args import filter_clang_args


class FilterClangArgsTest(unittest.TestCase):

  def test_filters_emscripten_version_check_only(self):
    self.assertEqual(
        [
            '-Wall',
            '-Wno-version-check-extra',
            '-Werror',
        ],
        filter_clang_args([
            '-Wall',
            '-Wno-version-check',
            '-Wno-version-check-extra',
            '-Werror',
        ]))


if __name__ == '__main__':
  unittest.main()

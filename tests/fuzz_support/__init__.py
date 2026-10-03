# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fuzz_support/__init__.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Test-only support for Issue #49 parser/tokenizer robustness evidence.

Authority order for expected behavior: ``docs/spec/pysh-language.md``, then the
#48 corpus ``tests/conformance/pysh-language-v1.json``, then existing production
behavior only where the specification leaves behavior implementation-defined.
Nothing here is a second semantic oracle and nothing here ships in the package.
"""
from __future__ import annotations

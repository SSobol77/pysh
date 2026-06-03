# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Siergej Sobolewski

"""Compatibility facade for PySH parser helpers.

Issue #8 split parser responsibilities into focused modules. Existing imports
from ``pysh.parsing.parser`` remain supported through these re-exports.
"""
from __future__ import annotations

from pysh.parsing.ast import ChainElement, ChainOp
from pysh.parsing.errors import ParseError, UnsupportedSyntaxError
from pysh.parsing.expansion import (
    DEFAULT_SUBSTITUTION_TIMEOUT_SECONDS,
    expand_command_substitution,
    expand_variables,
    is_unsupported_parameter_expansion,
)
from pysh.parsing.grammar import (
    parse_assignment,
    parse_leading_env_assignments,
    split_chain,
    split_pipeline,
    validate_unsupported_syntax,
)
from pysh.parsing.lexer import has_unbalanced_quotes, strip_comments
from pysh.parsing.multiline import (
    ContinuationKind,
    ContinuationState,
    NestedBlockError,
    UnterminatedBlockError,
    continuation_state,
    extract_block_body,
    has_trailing_line_continuation,
    is_block_closer,
    is_block_opener,
    iter_logical_lines,
    join_backslash_continuations,
    split_paste_commands,
)

__all__ = [
    "ChainElement",
    "ChainOp",
    "ContinuationKind",
    "ContinuationState",
    "DEFAULT_SUBSTITUTION_TIMEOUT_SECONDS",
    "NestedBlockError",
    "ParseError",
    "UnsupportedSyntaxError",
    "UnterminatedBlockError",
    "continuation_state",
    "expand_command_substitution",
    "expand_variables",
    "extract_block_body",
    "has_trailing_line_continuation",
    "has_unbalanced_quotes",
    "is_block_closer",
    "is_block_opener",
    "is_unsupported_parameter_expansion",
    "iter_logical_lines",
    "join_backslash_continuations",
    "parse_assignment",
    "parse_leading_env_assignments",
    "split_chain",
    "split_paste_commands",
    "split_pipeline",
    "strip_comments",
    "validate_unsupported_syntax",
]

# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: src/pysh/python_highlight.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Python syntax highlighting for the PySH Python Command Execution Layer.

Applies to ``#show``, ``#show file.py``, ``#edit``, and other Python
source rendering inside Python command mode.

Highlighting is **rendering-only**:

* source buffers are never modified;
* ANSI escape sequences are never written to files;
* code passed to the Python runtime is always clean source text.

Pygments is an optional dependency.  When it is not installed, all render
methods return the original source text unchanged so PySH works without it.

Install the highlighting extra to enable Pygments::

    pip install pysh-shell[highlighting]

or in development::

    uv sync
"""
from __future__ import annotations

import os
import sys
from typing import IO

# ---------------------------------------------------------------------------
# Optional Pygments import — full graceful fallback when not installed.
# ---------------------------------------------------------------------------
try:
    from pygments import highlight as _pygments_highlight
    from pygments.formatters import Terminal256Formatter
    from pygments.lexers import PythonLexer as _PythonLexer
    _PYGMENTS: bool = True
except ImportError:
    _PYGMENTS = False


def pygments_available() -> bool:
    """Return ``True`` when Pygments is installed and importable."""
    return _PYGMENTS


# ---------------------------------------------------------------------------
# TTY / color detection
# ---------------------------------------------------------------------------

def _tty_colors_ok(stream: IO[str] | None = None) -> bool:
    """Return ``True`` when ANSI colors are appropriate for *stream*.

    Checks ``NO_COLOR`` (any value disables), ``TERM=dumb`` / unset, and
    whether the stream is a real TTY.  Mirrors the logic in
    :func:`pysh.highlighting.colors_enabled`.
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    term = os.environ.get("TERM", "")
    if not term or term == "dumb":
        return False
    s = stream if stream is not None else sys.stdout
    try:
        return bool(s.isatty())
    except (AttributeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Shared renderer
# ---------------------------------------------------------------------------

class PythonSyntaxRenderer:
    """Render Python source with optional terminal syntax highlighting.

    Highlighting is rendering-only.  The source buffer, saved files, and
    code executed by the runtime are never touched.

    Highlighting is automatically disabled for non-TTY output unless
    *force_color* is ``True``.  When Pygments is not installed every render
    method returns the original text unchanged — PySH keeps working.

    Parameters
    ----------
    enabled:
        Master switch.  ``False`` → plain text always.
    force_color:
        Skip the TTY check and always emit ANSI (useful in focused tests).
    theme:
        Pygments style name, e.g. ``"monokai"``, ``"dracula"``.
    stream:
        Output stream used for the TTY check; ``None`` falls back to
        ``sys.stdout`` at render time.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        force_color: bool = False,
        theme: str = "monokai",
        stream: IO[str] | None = None,
    ) -> None:
        self._enabled = enabled
        self._force_color = force_color
        self._theme = theme
        self._stream = stream

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_code(self, source: str) -> str:
        """Return *source* with terminal syntax highlighting applied.

        Returns *source* unchanged when:

        * highlighting is disabled (``enabled=False``);
        * Pygments is not installed;
        * the output stream is not a TTY and ``force_color`` is ``False``;
        * any exception occurs during highlighting.

        The trailing newline that Pygments appends is stripped before
        returning so callers control their own line-ending policy.
        """
        if not self._active():
            return source
        try:
            formatter = Terminal256Formatter(style=self._theme)
            result = _pygments_highlight(source, _PythonLexer(), formatter)
            return result.rstrip("\n")
        except Exception:  # noqa: BLE001 - highlighting must never crash PySH
            return source

    def render_line(self, line: str) -> str:
        """Highlight a single Python source line.

        Convenience wrapper around :meth:`render_code` for callers that
        process lines individually.
        """
        return self.render_code(line)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _active(self) -> bool:
        """Return True when highlighting should be applied."""
        if not self._enabled:
            return False
        if not _PYGMENTS:
            return False
        if self._force_color:
            return True
        return _tty_colors_ok(self._stream)

    # ------------------------------------------------------------------
    # Introspection (useful in tests)
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Master enable flag passed to the constructor."""
        return self._enabled

    @property
    def pygments_installed(self) -> bool:
        """``True`` when Pygments was successfully imported."""
        return _PYGMENTS

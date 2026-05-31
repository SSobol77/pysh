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
"""Python terminal rendering for the PySH Python Command Execution Layer.

Applies to interactive Python input, continuation prompts, ``#show``,
``#show file.py``, ``#edit``, diagnostics, and status/help text inside Python
command mode.

Highlighting is **rendering-only**:

* source buffers are never modified;
* ANSI escape sequences are never written to files;
* code passed to the Python runtime is always clean source text.

Pygments is a normal runtime dependency for PySH v0.5.0 and later. A defensive
plain-text fallback remains so terminal rendering can never crash the shell.
"""
from __future__ import annotations

import re
from typing import IO

from pysh.highlighting import colors_enabled, paint

# ---------------------------------------------------------------------------
# Defensive Pygments import — the package depends on it at runtime, but render
# failures must never crash PySH.
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

_EXCEPTION_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning))(:.*)?$")


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

    def render_prompt(self, prompt: str) -> str:
        """Render a Python command-mode prompt."""
        if not self._active():
            return prompt
        if prompt.startswith("..."):
            return paint(prompt, "warn", enabled=True)
        if prompt.startswith("[") and ":edit]" in prompt:
            close = prompt.find("]") + 1
            if close > 0:
                return (
                    paint(prompt[:close], "info", enabled=True)
                    + paint(prompt[close:], "builtin", enabled=True)
                )
        return paint(prompt, "builtin", enabled=True)

    def render_error(self, text: str) -> str:
        """Render Python syntax/runtime diagnostic text."""
        if not self._active():
            return text
        return "\n".join(self.render_exception_line(line) for line in text.splitlines())

    def render_status(self, text: str) -> str:
        """Render Python mode status/help text."""
        if not self._active():
            return text
        return paint(text, "info", enabled=True)

    def render_exception_line(self, line: str) -> str:
        """Highlight the exception class in a single diagnostic line."""
        if not self._active():
            return line
        match = _EXCEPTION_LINE_RE.match(line)
        if match is None:
            if line.lstrip().startswith("^"):
                return paint(line, "error", enabled=True)
            return line
        name = match.group(1)
        suffix = match.group(2) or ""
        return f"{paint(name, 'error', enabled=True)}{suffix}"

    def render_traceback(self, text: str) -> str:
        """Render a traceback or exception-only diagnostic block."""
        return self.render_error(text)

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
        return colors_enabled(self._stream)

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

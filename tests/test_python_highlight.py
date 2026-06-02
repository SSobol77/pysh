# SPDX-License-Identifier: GPL-3.0-or-later
#
# Project: PySH - Python-first interactive shell for Debian and Unix-like systems
# File: tests/test_python_highlight.py
# Repository: https://github.com/SSobol77/pysh
# PyPI: https://pypi.org/project/pysh-shell
#
# Copyright (c) 2026 Siergej Sobolewski
#
# Licensed under the GNU General Public License v3.0 or later.
# See the LICENSE file in the project root for full license text.
"""Tests for the Python syntax highlighting renderer and its integration
with Python command mode (#show, #show file.py, #edit)."""
from __future__ import annotations

import io
import tomllib
from pathlib import Path

import pytest

import pysh.python_layer.highlighting as _mod
from pysh.python_layer.highlighting import PythonSyntaxRenderer, pygments_available
from pysh.python_layer.mode import PythonCommandMode

# ─── helpers ────────────────────────────────────────────────────────────────

def _disabled_renderer() -> PythonSyntaxRenderer:
    return PythonSyntaxRenderer(enabled=False)


def _forced_renderer() -> PythonSyntaxRenderer:
    """Renderer that always emits ANSI (force_color=True)."""
    return PythonSyntaxRenderer(force_color=True)


def _mode_forced(
    lines: list[str],
    *,
    cwd: Path | None = None,
) -> tuple[PythonCommandMode, io.StringIO, io.StringIO]:
    out = io.StringIO()
    err = io.StringIO()
    mode = PythonCommandMode(
        input_source=lines,
        out_stream=out,
        err_stream=err,
        renderer=_forced_renderer(),
        cwd_provider=(lambda: cwd) if cwd is not None else None,
    )
    return mode, out, err


def _has_ansi(text: str) -> bool:
    return "\x1b[" in text


def _mode_plain(lines: list[str], *, cwd: Path | None = None) -> tuple[PythonCommandMode, io.StringIO, io.StringIO]:
    out = io.StringIO()
    err = io.StringIO()
    mode = PythonCommandMode(
        input_source=lines,
        out_stream=out,
        err_stream=err,
        cwd_provider=(lambda: cwd) if cwd is not None else None,
    )
    return mode, out, err


# ═══════════════════════════════════════════════════════════════════════════
# PythonSyntaxRenderer — unit tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRendererDisabled:
    def test_render_code_returns_source_unchanged(self) -> None:
        r = _disabled_renderer()
        src = "x = 1\nprint(x)\n"
        assert r.render_code(src) == src

    def test_render_line_returns_line_unchanged(self) -> None:
        r = _disabled_renderer()
        assert r.render_line("x = 1") == "x = 1"

    def test_no_ansi_in_disabled_output(self) -> None:
        r = _disabled_renderer()
        assert not _has_ansi(r.render_code("import math\nprint(math.pi)"))

    def test_enabled_property_is_false(self) -> None:
        r = _disabled_renderer()
        assert r.enabled is False


class TestRendererPygmentsFallback:
    """Simulate Pygments being unavailable."""

    def test_returns_source_when_pygments_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_PYGMENTS", False)
        r = PythonSyntaxRenderer(force_color=True)  # force_color won't help
        src = "x = 1\n"
        assert r.render_code(src) == src

    def test_no_ansi_when_pygments_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_PYGMENTS", False)
        r = PythonSyntaxRenderer(force_color=True)
        assert not _has_ansi(r.render_code("print('hello')"))

    def test_pygments_available_reflects_monkeypatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_PYGMENTS", False)
        assert not pygments_available()


class TestRendererEnabled:
    """Tests that require Pygments to be actually installed."""

    @pytest.mark.skipif(not pygments_available(), reason="Pygments not installed")
    def test_force_color_returns_ansi(self) -> None:
        r = _forced_renderer()
        result = r.render_code("x = 1")
        assert _has_ansi(result)

    @pytest.mark.skipif(not pygments_available(), reason="Pygments not installed")
    def test_source_content_preserved_in_highlighted_output(self) -> None:
        r = _forced_renderer()
        result = r.render_code("x = 42")
        # The literal content is present even within ANSI sequences.
        assert "42" in result

    @pytest.mark.skipif(not pygments_available(), reason="Pygments not installed")
    def test_no_trailing_newline_added(self) -> None:
        r = _forced_renderer()
        result = r.render_code("x = 1")
        # render_code strips the trailing newline Pygments appends.
        assert not result.endswith("\n")

    @pytest.mark.skipif(not pygments_available(), reason="Pygments not installed")
    def test_render_line_produces_ansi(self) -> None:
        r = _forced_renderer()
        assert _has_ansi(r.render_line("import os"))

    @pytest.mark.skipif(not pygments_available(), reason="Pygments not installed")
    def test_theme_monokai_default(self) -> None:
        r = PythonSyntaxRenderer(force_color=True)
        # Must not crash; any ANSI output accepted.
        result = r.render_code("1 + 1")
        assert isinstance(result, str)

    def test_pysh_color_zero_disables_renderer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYSH_COLOR", "0")
        monkeypatch.delenv("NO_COLOR", raising=False)
        stream = io.StringIO()
        stream.isatty = lambda: True  # type: ignore[attr-defined]
        r = PythonSyntaxRenderer(stream=stream)
        assert not _has_ansi(r.render_code("x = 1"))

    def test_no_color_disables_renderer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("PYSH_COLOR", "always")
        r = PythonSyntaxRenderer(force_color=False)
        assert not _has_ansi(r.render_code("x = 1"))

    def test_pysh_color_always_forces_renderer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("PYSH_COLOR", "always")
        monkeypatch.setenv("TERM", "dumb")
        r = PythonSyntaxRenderer(force_color=False, stream=io.StringIO())
        assert _has_ansi(r.render_code("x = 1"))

    def test_prompt_rendering_adds_ansi_when_forced(self) -> None:
        r = _forced_renderer()
        assert _has_ansi(r.render_prompt(">>> "))
        assert _has_ansi(r.render_prompt("... "))
        assert _has_ansi(r.render_prompt("[file.py:edit] >>> "))

    def test_error_rendering_adds_ansi_when_forced(self) -> None:
        r = _forced_renderer()
        assert _has_ansi(r.render_error("SyntaxError: expected '('\n"))
        assert _has_ansi(r.render_error("NameError: name 'show' is not defined\n"))


class TestRendererSafety:
    def test_incomplete_python_no_crash(self) -> None:
        r = _forced_renderer() if pygments_available() else _disabled_renderer()
        result = r.render_code("def f(")  # incomplete
        assert isinstance(result, str)

    def test_invalid_python_no_crash(self) -> None:
        r = _forced_renderer() if pygments_available() else _disabled_renderer()
        result = r.render_code("!!!invalid!!!")
        assert isinstance(result, str)

    def test_empty_source_no_crash(self) -> None:
        r = _forced_renderer() if pygments_available() else _disabled_renderer()
        assert r.render_code("") == ""

    def test_multiline_source_no_crash(self) -> None:
        r = _forced_renderer() if pygments_available() else _disabled_renderer()
        src = "class Foo:\n    def bar(self):\n        return 42\n"
        result = r.render_code(src)
        assert isinstance(result, str)
        # Source content preserved.
        assert "Foo" in result
        assert "bar" in result

    def test_exception_in_formatter_returns_plain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not pygments_available():
            pytest.skip("Pygments not installed")

        def _boom(*_a, **_kw):  # type: ignore[no-untyped-def]
            raise RuntimeError("formatter exploded")

        monkeypatch.setattr(_mod, "_pygments_highlight", _boom)
        r = PythonSyntaxRenderer(force_color=True)
        src = "x = 1"
        assert r.render_code(src) == src


# ═══════════════════════════════════════════════════════════════════════════
# Integration: buffer purity (#show, #save, #run, #edit)
# ═══════════════════════════════════════════════════════════════════════════

class TestBufferPurity:
    """ANSI escapes must never appear in the source buffer, saved files, or
    code passed to the runtime."""

    def test_show_does_not_modify_buffer(self) -> None:
        mode, out, err = _mode_plain(["x = 1", "#show", "#exit"])
        mode.run()
        # Buffer must contain clean source, not ANSI.
        assert not any(_has_ansi(ln) for ln in mode._buffer)

    def test_show_file_does_not_modify_buffer(self, tmp_path: Path) -> None:
        f = tmp_path / "pure.py"
        f.write_text("y = 2\n", encoding="utf-8")
        mode, out, err = _mode_plain(["x = 1", "#show pure.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert not any(_has_ansi(ln) for ln in mode._buffer)

    def test_show_file_does_not_change_active_file(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("a = 1\n", encoding="utf-8")
        f2.write_text("b = 2\n", encoding="utf-8")
        mode, out, err = _mode_plain(["#open a.py", "#show b.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert mode._active_file is not None
        assert mode._active_file.name == "a.py"

    def test_save_writes_clean_source(self, tmp_path: Path) -> None:
        mode, out, err = _mode_plain(
            ['x = "hello"', "#save out.py", "#exit"], cwd=tmp_path
        )
        mode.run()
        content = (tmp_path / "out.py").read_text(encoding="utf-8")
        assert not _has_ansi(content)
        assert 'x = "hello"' in content

    def test_save_after_open_writes_clean_source(self, tmp_path: Path) -> None:
        script = tmp_path / "clean.py"
        script.write_text("a = 1\nb = 2\n", encoding="utf-8")
        mode, out, err = _mode_plain(["#open clean.py", "#save", "#exit"], cwd=tmp_path)
        mode.run()
        content = script.read_text(encoding="utf-8")
        assert not _has_ansi(content)

    def test_run_executes_clean_source(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mode, out, err = _mode_plain(['print("clean_run")', "#run", "#exit"])
        mode.run()
        cap = capsys.readouterr()
        assert "clean_run" in cap.out
        assert not _has_ansi(cap.out)

    def test_edit_does_not_modify_buffer(self) -> None:
        mode, out, err = _mode_plain(["x = 1", "#edit", "#exit"])
        mode.run()
        assert not any(_has_ansi(ln) for ln in mode._buffer)

    def test_edit_shows_buffer_content(self) -> None:
        mode, out, err = _mode_plain(["x = 42", "#edit", "#exit"])
        mode.run()
        text = out.getvalue()
        assert "x = 42" in text

    def test_edit_empty_buffer(self) -> None:
        mode, out, err = _mode_plain(["#edit", "#exit"])
        mode.run()
        assert "buffer empty" in out.getvalue()


class TestHighlightingInTestMode:
    """Injected StringIO streams are not TTYs → highlighting disabled by default."""

    def test_show_output_has_no_ansi_by_default(self) -> None:
        mode, out, err = _mode_plain(["x = 1", "#show", "#exit"])
        mode.run()
        numbered_lines = [ln for ln in out.getvalue().splitlines() if " | " in ln]
        assert all(not _has_ansi(ln) for ln in numbered_lines)

    def test_renderer_disabled_for_stringio(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        mode = PythonCommandMode(
            input_source=["#exit"],
            out_stream=out,
            err_stream=err,
        )
        # StringIO has no isatty() → _tty_colors_ok returns False.
        assert not mode._renderer._active()

    def test_force_color_renderer_emits_ansi_in_tests(self) -> None:
        if not pygments_available():
            pytest.skip("Pygments not installed")
        r = PythonSyntaxRenderer(force_color=True)
        assert _has_ansi(r.render_code("x = 1"))

    def test_entered_interactive_line_is_echoed_highlighted_when_forced(self) -> None:
        mode, out, err = _mode_forced(["1+3", "#exit"])
        mode.run()
        assert _has_ansi(out.getvalue())
        assert "1" in out.getvalue()

    def test_entered_continuation_line_is_echoed_highlighted_when_forced(self) -> None:
        mode, out, err = _mode_forced(["def add(a, b):", "    return a + b", "", "#exit"])
        mode.run()
        text = out.getvalue()
        assert _has_ansi(text)
        assert "return" in text

    def test_show_highlights_when_forced(self) -> None:
        mode, out, err = _mode_forced(["x = 1", "#show", "#exit"])
        mode.run()
        numbered_lines = [ln for ln in out.getvalue().splitlines() if " | " in ln]
        assert numbered_lines
        assert any(_has_ansi(ln) for ln in numbered_lines)

    def test_show_file_highlights_when_forced(self, tmp_path: Path) -> None:
        (tmp_path / "view.py").write_text("x = 1\n", encoding="utf-8")
        mode, out, err = _mode_forced(["#show view.py", "#exit"], cwd=tmp_path)
        mode.run()
        assert _has_ansi(out.getvalue())

    def test_edit_highlights_when_forced(self) -> None:
        mode, out, err = _mode_forced(["x = 1", "#edit", "#exit"])
        mode.run()
        assert _has_ansi(out.getvalue())

    @pytest.mark.parametrize(
        "inputs",
        [
            ["def sum:", "#exit"],
            ["if True:", "pass", "#exit"],
            ["show()", "#exit"],
        ],
    )
    def test_python_errors_are_highlighted_when_forced(self, inputs: list[str]) -> None:
        mode, out, err = _mode_forced(inputs)
        mode.run()
        assert _has_ansi(err.getvalue())


def test_pygments_is_required_runtime_dependency() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]
    extras = data["project"].get("optional-dependencies", {})

    assert any(dep.startswith("pygments") for dep in dependencies)
    assert "highlighting" not in extras


class TestHelpMentionsHighlighting:
    def test_help_mentions_highlighting(self) -> None:
        mode, out, err = _mode_plain(["#help", "#exit"])
        mode.run()
        text = out.getvalue()
        assert "highlight" in text.lower()

    def test_help_mentions_visual_only(self) -> None:
        mode, out, err = _mode_plain(["#help", "#exit"])
        mode.run()
        text = out.getvalue().lower()
        assert "visual" in text or "never saved" in text or "not saved" in text

    def test_help_mentions_edit_directive(self) -> None:
        mode, out, err = _mode_plain(["#help", "#exit"])
        mode.run()
        assert "#edit" in out.getvalue()

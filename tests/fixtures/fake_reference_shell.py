# SPDX-License-Identifier: GPL-2.0-only
# File: tests/fixtures/fake_reference_shell.py
#
# Copyright (C) 2026 Siergej Sobolewski

"""Repository-owned FAKE reference shell for the differential-laboratory unit tests.

It imitates only the startup behavior the laboratory's isolation checks probe, so
those checks can be exercised (including failure modes) without a real Bash, Zsh
or Fish. It is selected by file name: ``bash``/``zsh``/``fish`` behave correctly;
``<shell>_<variant>`` adds one defect:

* ``bash_leaky``       ignores ``--norc``/``--noprofile`` and reads ``.bashrc``
* ``zsh_noisy``        its "global zshenv" prints noise
* ``zsh_pathmut``      its "global zshenv" rewrites ``PATH``
* ``zsh_leaky``        ignores ``-f``
* ``fish_confd``       ``--no-config`` still reads ``conf.d/*.fish``

Commands are executed by the platform ``/bin/sh``; this is test equipment only.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys


def run_file(path: str) -> None:
    if os.path.isfile(path):
        sys.stdout.write(subprocess.run(["/bin/sh", path], capture_output=True, text=True, check=False).stdout)
        sys.stdout.flush()


def main(argv: list[str]) -> int:
    kind, _, variant = os.path.basename(argv[0]).partition("_")
    args = argv[1:]
    if args == ["--version"]:
        print(f"{kind}, version fake-1.0")
        return 0
    home = os.environ.get("HOME", "")
    flags = [a for a in args if a != "-c"]
    command = args[args.index("-c") + 1] if "-c" in args else ""
    flags = flags[: len(flags) - (1 if command else 0)]
    login = "-l" in flags
    env = dict(os.environ)

    if kind == "bash":
        isolated = ("--norc" in flags and "--noprofile" in flags) and variant != "leaky"
        hook = env.get("BASH_ENV")
        if hook:
            run_file(hook)  # real bash honors BASH_ENV even with --norc
        if login and "--noprofile" not in flags:
            for name in (".bash_profile", ".bash_login", ".profile"):
                if os.path.isfile(os.path.join(home, name)):
                    run_file(os.path.join(home, name))
                    break
        if not isolated:
            run_file(os.path.join(home, ".bashrc"))
    elif kind == "zsh":
        if variant == "noisy":
            print("GLOBAL-ZSHENV-NOISE")
        if variant == "pathmut":
            env["PATH"] = "/usr/bin:" + env.get("PATH", "")
        zdot = env.get("ZDOTDIR") or home
        if "-f" not in flags or variant == "leaky":
            run_file(os.path.join(zdot, ".zshenv"))
            if login:
                run_file(os.path.join(zdot, ".zprofile"))
                run_file(os.path.join(zdot, ".zlogin"))
    elif kind == "fish":
        if "--no-config" not in flags or variant == "confd":
            base = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
            if "--no-config" not in flags:
                run_file(os.path.join(base, "fish", "config.fish"))
            for path in sorted(glob.glob(os.path.join(base, "fish", "conf.d", "*.fish"))):
                run_file(path)
    else:
        print(f"unknown fake shell: {kind}", file=sys.stderr)
        return 2
    done = subprocess.run(["/bin/sh", "-c", command], env=env, check=False)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))

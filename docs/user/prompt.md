<!--
SPDX-License-Identifier: GPL-2.0-only

Project: PySH - Python-first interactive shell for Debian and Unix-like systems
File: docs/user/prompt.md
Repository: https://github.com/SSobol77/pysh
PyPI: https://pypi.org/project/pysh-shell

Copyright (C) 2026 Siergej Sobolewski

-->

# Prompt

PySH Prompt Engine 2.0 is a bounded, stdlib-only prompt renderer integrated in
`src/pysh/core/shell.py`. It has two layouts:

- `two_line` (default): prints a framed information block, then gives readline
  only the closing command line.
- `single`: renders all enabled segments inline before the command symbol.

All prompt paths use repository-defined options from `~/.pyshrc.py`.

## Options

| Option | Default | Behavior |
| ------ | ------- | -------- |
| `show_user` | `True` | Show the current user. |
| `show_host` | `True` | Show the current host. |
| `show_cwd` | `True` | Show the current directory. |
| `cwd_style` | `"home"` | `full`, `home`, or `basename`. |
| `prompt_layout` | `"two_line"` | `two_line` or `single`. |
| `symbol` | `">"` | Command-line prompt symbol. |
| `show_virtualenv` | `True` | Show active `VIRTUAL_ENV` basename. |
| `show_git_branch` | `True` | Show Git branch or detached HEAD without invoking `git`. |
| `show_git_dirty` | `True` | Show conservative dirty marker for obvious metadata states. |
| `show_python_version` | `True` | Show active Python `pyX.Y`. |
| `show_uv_version` | `True` | Show cached bounded `uv --version`. |
| `show_ruff_version` | `True` | Show cached bounded `ruff --version`. |
| `show_rust_version` | `True` | Show cached bounded `rustc --version`. |
| `show_node_version` | `True` | Show cached bounded `node --version`. |
| `show_npm_version` | `True` | Show cached bounded `npm --version`. |
| `show_last_status` | `True` | Show non-zero previous exit status. |
| `show_command_duration` | `True` | Show last command duration at or above threshold. |
| `command_duration_threshold` | `0.5` | Non-negative seconds; accepts `int` or `float`, rejects `bool`. |
| `show_ssh_indicator` | `True` | Show `ssh` when SSH environment variables are present. |
| `show_aws_profile` | `False` | Opt-in `AWS_PROFILE` / `AWS_DEFAULT_PROFILE` display. |
| `show_k8s_context` | `False` | Opt-in Kubernetes current-context display. |
| `show_pip_version` | `False` | Opt-in cached bounded `pip --version`. |
| `show_docker_version` | `False` | Opt-in cached bounded `docker --version` (client only, no daemon contact). |
| `show_kubectl_version` | `False` | Opt-in cached bounded `kubectl --version` (client only, no cluster contact). |
| `show_ecli_version` | `False` | Opt-in cached bounded `ecli --version`. |
| `show_guardbsd_version` | `False` | Opt-in cached bounded `guardbsd --version`. |
| `show_aeronerve_version` | `False` | Opt-in cached bounded `aeronerve --version`. |

Example:

```python
def configure(shell):
    shell.set_prompt_option("show_command_duration", True)
    shell.set_prompt_option("command_duration_threshold", 1.0)
    shell.set_prompt_option("show_aws_profile", True)
    shell.set_prompt_option("show_k8s_context", True)
```

## Environment Segments

The SSH segment uses cheap environment checks only: `SSH_CLIENT`, `SSH_TTY`, or
`SSH_CONNECTION`.

The AWS segment never calls the AWS CLI and never reads credentials. It displays
only `AWS_PROFILE`, falling back to `AWS_DEFAULT_PROFILE`, and is off by
default.

The Kubernetes segment never calls `kubectl` and does not use PyYAML. It reads
`KUBECONFIG` or `~/.kube/config` with a bounded size limit, scans for a
top-level `current-context: NAME`, and omits the segment on missing, unreadable,
oversized, malformed, or multi-document input. When `KUBECONFIG` contains
multiple files, the first file defining `current-context` wins.

AWS and Kubernetes values are sanitized before rendering so control characters
and terminal escape sequences cannot be injected into the prompt.

## Tool-Version Segments (Issue #32)

`show_pip_version`, `show_docker_version`, `show_kubectl_version`,
`show_ecli_version`, `show_guardbsd_version`, and `show_aeronerve_version`
reuse the same `ToolVersionSpec` / `_detect_tool_version()` machinery as
`show_uv_version`, `show_ruff_version`, `show_rust_version`,
`show_node_version`, and `show_npm_version`. All six default to `False`:
Issue #32 integrations are optional, and enabling one is an explicit,
per-option opt-in.

Lazy detection contract, identical to the pre-existing tool-version segments:

- While the option is `False`, the tool is never probed: no `shutil.which`
  lookup, no `subprocess.run`, no cache entry populated.
- When the option is `True`, the executable is looked up with `shutil.which`
  first; a missing executable never spawns a subprocess.
- A found executable is probed once per shell session with a bounded
  timeout and an explicit argv list (`[executable, "--version"]`); the
  result (or the absence of one) is cached, so later prompt renders in the
  same session never re-probe.
- A missing executable, a non-zero exit, unparsable output, or a timeout all
  omit the segment silently -- no stderr, no diagnostic, no crash.

`show_kubectl_version` is unrelated to `show_k8s_context`: the former is a
cached, bounded `kubectl --version` client-version probe; the latter (from
Issue #27) reads `KUBECONFIG` / `~/.kube/config` directly and never invokes
`kubectl`. Enabling one has no effect on the other.

GuardBSD and AeroNerve are ecosystem tool names for the `show_guardbsd_version`
and `show_aeronerve_version` segments; PySH does not assume either binary is
installed, and neither segment renders anything unless the corresponding
executable is found on `PATH`.

## Colors

Prompt colors are segment-keyed and validated by `set_prompt_color()`. The new
segments use these defaults:

```python
shell.set_prompt_color("duration", "yellow")
shell.set_prompt_color("ssh", "fuchsia")
shell.set_prompt_color("aws", "orange")
shell.set_prompt_color("k8s", "aqua")
shell.set_prompt_color("pip", "navy")
shell.set_prompt_color("docker", "olive")
shell.set_prompt_color("kubectl", "gray")
shell.set_prompt_color("ecli", "silver")
shell.set_prompt_color("guardbsd", "maroon")
shell.set_prompt_color("aeronerve", "teal")
```

Use `fuchsia` instead of `magenta`, and `aqua` instead of `cyan`; `magenta` and
`cyan` are not valid names for PySH prompt color parsing. Hex colors such as
`#33CCFF` are also accepted. `NO_COLOR` and `TERM=dumb` continue to disable
color output.

## Manual Validation

Debian 13:

```sh
uv run pysh --version
uv run python -m pysh --version
AWS_PROFILE=dev uv run pysh -c "echo ok"
KUBECONFIG=/tmp/kubeconfig uv run pysh -c "echo ok"
```

FreeBSD 14+:

```sh
python3.13 -m pysh --version
python3.13 -m pysh -c "echo ok"
```

Expected behavior: prompt rendering must not call network tools, `aws`,
`kubectl`, or `git`; missing tools or malformed config must omit only the
affected segment.

Issue #32 integrations, enabled temporarily via `set_prompt_option`:

```sh
uv run python -c "
from pysh.core.shell import PyShell
shell = PyShell()
shell.set_prompt_option('show_pip_version', True)
shell.set_prompt_option('show_docker_version', True)
print(shell._prompt_info_line())
"
```

Only installed binaries render a segment; report exactly which binaries were
present on the machine used for manual validation (do not claim GuardBSD or
AeroNerve are installed unless they actually are).

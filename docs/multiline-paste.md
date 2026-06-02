# Multiline Paste and Command Chaining

PySH supports pasting newline-separated command blocks directly into an interactive session.  Each complete command is executed in order, as if the user had typed and submitted each one separately.

## Pasting a block of commands

Paste the following block into PySH:

```
python --version
pip --version
```

PySH executes:
1. `python --version`
2. `pip --version`

No manual confirmation is needed between commands.

### More examples

```
export FOO=bar
env
```

```
cd /tmp
pwd
```

```
FOO=bar env
BAR="hello world" env
```

## How it works

When you paste multiple lines, your terminal emulator delivers all bytes at once.  PySH's raw-mode line editor reads the entire chunk, returns the first complete command line, and queues the remaining commands.  Each subsequent call to the prompt returns the next queued command.

Commands that span multiple lines inside **quotes** are handled correctly — a newline inside `"..."` or `'...'` is part of the command, not a command boundary:

```
echo "hello
world"
```

This is executed as a single command.

## Bracketed paste mode

Most modern terminal emulators support [bracketed paste mode](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Bracketed-Paste-Mode).  When active, the terminal wraps pasted text with:

```
ESC [ 200 ~   ← paste start
pasted text
ESC [ 201 ~   ← paste end
```

PySH recognises these markers and collects the entire paste block before splitting it into commands.  This ensures that:

- The paste-start and paste-end markers never appear in the command buffer or in executed commands.
- Newlines inside quoted strings in the pasted text are not treated as command boundaries.
- The full paste is split atomically, so no partial commands are executed.

## Semicolon command chaining

Commands can also be chained on a single line using semicolons:

```sh
python --version; pip --version
```

This is equivalent to the two-line paste above.  Semicolons inside single or double quotes are literal:

```sh
echo "a;b"    # prints: a;b
echo 'c;d'    # prints: c;d
```

## Temporary environment assignments

A `NAME=value` prefix before a command sets that variable only for the child process:

```sh
FOO=bar env           # env sees FOO=bar; parent shell does not
BAR="hello world" env # BAR is set with a space; parent shell unchanged
SHELL=/bin/bash env   # env sees SHELL=/bin/bash; parent shell unchanged
```

Multiple assignments before a command are all applied:

```sh
FOO=1 BAR=2 env
```

Assignments without a command update PySH's local variable table:

```sh
FOO=bar BAR=baz      # updates local vars only, does not export
echo $FOO            # prints: bar
```

These can be combined with paste and semicolons naturally:

```sh
python --version; pip --version
```

Midnight Commander is handled by PySH's `mc` wrapper.  See
`docs/midnight-commander.md` for the MC subshell policy.

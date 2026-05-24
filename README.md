<!-- SPDX-License-Identifier: Apache-2.0

Project: PYSH - Python-first interactive shell for Debian and Unix-like systems
File: README.md

Copyright (c) 2026 Siergej Sobolewski
Licensed under the GNU General Public License v3.0 or later.
See the LICENSE file in the project root for full license text.
-->

# PYSH

## Python-first interactive shell for Debian and Unix-like systems

PYSH is a modern, Python-first interactive shell designed for Debian and Unix-like systems. It combines the power of Python with the convenience of a traditional shell, providing users with a seamless command-line experience.

## Features

## Run locally

```bash
python3 -m pysh
````

## Development install

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

Unix command:

```bash
ls -la
git status
cd ~/Code
```

Python command:

```bash
:Path.cwd()
:x = 10
:x * 2
```

## Build package

```bash
python -m pip install build twine
python -m build
twine check dist/*
```

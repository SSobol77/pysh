# SPDX-License-Identifier: GPL-3.0-or-later
# RPM spec for PySH. Mirrors the Debian package layout: pure-Python
# install under /opt/pysh-shell with a wrapper at /usr/bin/pysh.

%global pysh_app_prefix /opt/pysh-shell

Name:           pysh-shell
Version:        %{?pysh_version:%{pysh_version}}%{!?pysh_version:0.0.0}
Release:        1%{?dist}
Summary:        Fast, Python-first universal interactive shell

License:        GPL-3.0-or-later
URL:            https://github.com/SSobol77/pysh
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  coreutils

Requires:       python3 >= 3.13

%description
PySH is a fast, Python-first universal interactive shell for Debian
and Unix-like systems. It provides a Bash-style interactive REPL,
quote-aware command parsing, pipelines, redirection, command
substitution, a persistent Python runtime accessible via the "py"
builtin, Debian/system profile helpers, and a static migration layer
for sh/bash/zsh aliases and simple profile entries.

PySH is implemented in pure Python (standard library only) and
installs under /opt/pysh-shell with a wrapper at /usr/bin/pysh.

%prep
%setup -q -n %{name}-%{version}

%build
# Pure-Python package: nothing to compile here.

%install
rm -rf %{buildroot}
install -d -m 0755 %{buildroot}%{pysh_app_prefix}/lib/pysh
install -d -m 0755 %{buildroot}/usr/bin

# Install the package source tree under /opt/pysh-shell/lib/pysh
cp -a src/pysh/. %{buildroot}%{pysh_app_prefix}/lib/pysh/
# Drop any __pycache__ that may have crept in
find %{buildroot}%{pysh_app_prefix}/lib/pysh -type d -name __pycache__ -prune \
    -exec rm -rf {} +

# Install the wrapper command
install -m 0755 packaging/wrappers/pysh.sh %{buildroot}/usr/bin/pysh

%files
%license LICENSE
%doc README.md
%dir %{pysh_app_prefix}
%dir %{pysh_app_prefix}/lib
%{pysh_app_prefix}/lib/pysh
/usr/bin/pysh

%changelog
* Sat May 24 2026 Siergej Sobolewski <ssobo77@gmail.com> - 0.3.0-1
- Initial RPM packaging for PySH (pysh-shell) following the canonical
  packaging naming contract: pysh-shell-X.Y.Z-1.noarch.rpm.

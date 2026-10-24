#!/usr/bin/env bash
# Prepare a local checkout only. Never start Python entrypoints or systemd.
set -euo pipefail
umask 077
case "${1:-}" in
  "") install_deps=false ;;
  --install-deps) install_deps=true ;;
  *) echo "Usage: bash install.sh [--install-deps]" >&2; exit 2 ;;
esac
if (( $# > 1 )); then echo "Too many arguments" >&2; exit 2; fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -L .env || ( -e .env && ! -f .env ) ]]; then
  echo "Refusing non-regular .env" >&2; exit 1
fi
if [[ ! -e .env ]]; then
  # noclobber also protects against an existing file appearing during setup.
  ( set -o noclobber; cat .env.example > .env )
  echo "Created private .env with empty credentials."
else
  echo "Existing .env preserved."
fi
if [[ "$install_deps" == true ]]; then
  python_bin="${PYTHON_BIN:-python3}"
  "$python_bin" -c 'import sys; assert sys.version_info >= (3, 10), "Python >= 3.10 required"'
  if [[ -L .venv || ( -e .venv && ! -d .venv ) ]]; then
    echo "Refusing non-directory or symlink .venv" >&2; exit 1
  fi
  if [[ ! -d .venv ]]; then "$python_bin" -m venv .venv; fi
  .venv/bin/python -m pip install -r requirements.txt
fi
echo "Prepared only: no login, booking, key creation, service registration or start."
echo "Deployment instructions: docs/local-configuration.md"

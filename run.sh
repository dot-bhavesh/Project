#!/usr/bin/env bash
set -e
cd /home/bhavesh/Project
if [ "${1:-}" = "--cli" ]; then
  shift
  exec ./venv/bin/python main.py "$@"
fi
exec ./venv/bin/python menu.py "$@"

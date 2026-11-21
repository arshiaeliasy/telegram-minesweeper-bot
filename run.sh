#!/usr/bin/env bash
# اجرای ربات مین‌روب
set -euo pipefail
cd "$(dirname "$0")"
exec python3 bot.py "$@"

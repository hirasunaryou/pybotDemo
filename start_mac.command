#!/bin/bash
set -u
cd "$(dirname "$0")"
echo "================================"
echo " PyBot Live Lab / macOS"
echo "================================"
if command -v python3 >/dev/null 2>&1; then
  python3 launch.py
else
  echo "Python 3.8以上が必要です: https://www.python.org/downloads/"
  read -r -p "Enterキーで閉じます..."
  exit 1
fi
code=$?
if [ "$code" -ne 0 ]; then
  echo "エラー終了 (code=$code)"
  read -r -p "Enterキーで閉じます..."
fi
exit "$code"

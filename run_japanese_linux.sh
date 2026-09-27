#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -lt 1 ]]; then
  echo "用法：./run_japanese_linux.sh 视频文件 [其他参数]"
  exit 2
fi
.venv/bin/python main.py "$@" --ja-only

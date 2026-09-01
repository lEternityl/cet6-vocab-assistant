#!/bin/zsh
set -e

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

PYTHON_BIN="$(command -v python3)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "未找到 Python 3，请先安装 Python 3.11 或更高版本。"
  read -k 1 "?按任意键关闭…"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install -r backend/requirements.txt
echo "安装完成。以后双击 start.command 即可启动。"
read -k 1 "?按任意键关闭…"


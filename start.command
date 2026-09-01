#!/bin/zsh
set -e

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

if curl --silent --fail "http://127.0.0.1:8001/api/health" >/dev/null 2>&1; then
  open "http://127.0.0.1:8001/"
  exit 0
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "首次运行，正在安装本地依赖…"
  zsh "$PROJECT_DIR/setup.command" </dev/tty
fi

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

cd backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 &
SERVER_PID=$!

for _ in {1..40}; do
  if curl --silent --fail "http://127.0.0.1:8001/api/health" >/dev/null 2>&1; then
    open "http://127.0.0.1:8001/"
    echo "六级词汇学习助手已启动。关闭此窗口即可停止服务。"
    wait "$SERVER_PID"
    exit 0
  fi
  sleep 0.25
done

echo "启动失败，请检查 8001 端口是否被占用。"
wait "$SERVER_PID"


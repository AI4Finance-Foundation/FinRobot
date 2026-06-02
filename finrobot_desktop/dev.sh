#!/usr/bin/env bash
# dev.sh — FinRobot 本地开发启动器（live 后端源码 + 前端，无打包）。
#
# 每次运行 = 干净重启：先杀掉旧的 live 后端 / vite，再把两端拉起来。
# 后端跑 finrobot 源码（加载 .env、含 /api/debate、含 LLM key），改完后端代码重跑本脚本即生效。
# 前端 vite HMR，改完即时热更。
#
# 两种姿势（后端始终是 live 源码，区别只在前端壳子）：
#   ./dev.sh         浏览器姿势 — 前端跑在浏览器 http://localhost:5173
#   ./dev.sh --app   桌面 App 姿势 — 前端跑在 Tauri 原生窗口（cargo tauri dev）
#
# --app 走的仍是 live 后端：靠 FINROBOT_DEV_LIVE_BACKEND=1 让 Tauri 壳子跳过
# 冻结的 PyInstaller sidecar，窗口经 vite proxy 直连本脚本拉起的活后端（改 py 立即生效）。
# 不传 --app 时绝不碰 cargo tauri dev。
#
# 用法：  ./dev.sh [--app]   （Ctrl+C 同时停前后端 / App）

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_PORT=8321
FRONTEND_PORT=5173
BACKEND_LOG=/tmp/finrobot-backend.log

# ── 前端壳子：browser（默认）| app（Tauri 原生窗口）─────────────────────────
FRONTEND_MODE=browser
case "${1:-}" in
  --app) FRONTEND_MODE=app ;;
  "")    ;;
  *) echo "未知参数：$1（用法：./dev.sh [--app]）" >&2; exit 2 ;;
esac

# ── 选后端可执行：优先 venv 里的 finrobot，回退 uv run ──────────────────────
if [ -x ".venv/bin/finrobot" ]; then
  BACKEND_CMD=(.venv/bin/finrobot serve --host 127.0.0.1 --port "$BACKEND_PORT")
else
  BACKEND_CMD=(uv run finrobot serve --host 127.0.0.1 --port "$BACKEND_PORT")
fi

# ── 杀掉某端口上的监听进程（macOS 安全，不用 xargs -r）──────────────────────
kill_port() {
  local port="$1" pids
  pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null
  fi
}

echo "▸ 停掉旧的 live 后端 / vite ..."
pkill -f "finrobot serve" 2>/dev/null
pkill -f "ui/node_modules/.bin/vite" 2>/dev/null
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
sleep 1

# ── 启动 live 后端（后台）─────────────────────────────────────────────────
echo "▸ 启动 live 后端（源码, :${BACKEND_PORT}），日志 → ${BACKEND_LOG}"
"${BACKEND_CMD[@]}" >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Ctrl+C / 退出时一并停后端
cleanup() {
  echo
  echo "▸ 停止后端 (pid $BACKEND_PID) ..."
  kill "$BACKEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

# ── 等后端就绪（FastAPI 的 /openapi.json 一定有）────────────────────────────
echo -n "  等待后端就绪 "
READY=""
for i in $(seq 1 60); do
  if curl -sf -m 2 "http://127.0.0.1:${BACKEND_PORT}/openapi.json" >/dev/null 2>&1; then
    READY=1
    echo "✓ (pid $BACKEND_PID)"
    break
  fi
  # 后端进程已死（多半 .env / key 问题）→ 直接报日志退出
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "✗ 后端进程已退出"
    echo "──── $BACKEND_LOG 末尾 ────"
    tail -25 "$BACKEND_LOG"
    exit 1
  fi
  echo -n "."
  sleep 1
done
if [ -z "$READY" ]; then
  echo "✗ 60s 内未就绪，看 $BACKEND_LOG"
  tail -25 "$BACKEND_LOG"
  kill "$BACKEND_PID" 2>/dev/null
  exit 1
fi

# ── 启动 live 前端（前台，Ctrl+C 触发 cleanup 停后端）──────────────────────
if [ "$FRONTEND_MODE" = app ]; then
  echo "▸ 启动桌面 App（Tauri 窗口，vite :${FRONTEND_PORT} + 活后端 :${BACKEND_PORT}）"
  echo "  首次会编译 Rust 壳子，要等几分钟；之后秒开"
  echo "  (Ctrl+C 同时停 App / vite / 后端)"
  echo
  # FINROBOT_DEV_LIVE_BACKEND=1 → Tauri 壳子跳过冻结 sidecar，窗口直连上面的活后端。
  # cargo tauri dev 自己经 beforeDevCommand（npm run dev，cwd=ui/）拉 vite 并开窗口。
  FINROBOT_DEV_LIVE_BACKEND=1 cargo tauri dev
else
  echo "▸ 启动 live 前端（vite, :${FRONTEND_PORT}）"
  echo "  浏览器打开 → http://localhost:${FRONTEND_PORT}"
  echo "  (Ctrl+C 同时停前后端)"
  echo
  cd ui && npm run dev
fi

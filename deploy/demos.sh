#!/bin/bash
# Run the local-model web demo on this Mac (see web/README-hotel.md):
#   hotelbooking.wormhole.work -> web :3100 -> agent "hotel-local" (local MLX models, .env.local)
# The Cloudflare Tunnel (cloudflared system service) maps the hostname to the port.
# The cloud Taiwan-Mandarin demo (hotel-tw.wormhole.work) doesn't run here: its web app is a
# Cloudflare Worker and its agent is hosted on LiveKit Cloud (issue #16).
# The local worker also needs the MLX servers (mlx_lm.server :8080, mlx_audio.server :8000).
#
# usage: deploy/demos.sh start|stop|status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/deploy/logs"
PY="$ROOT/.venv/bin/python"
PNPM=(npx -y pnpm@9.15.9)
mkdir -p "$LOGS"

start() {
  cd "$ROOT/hotel_receptionist"
  # Local-model agent: backends/language from .env.local.
  AGENT_NAME=hotel-local AGENT_IDLE_PROCESSES=1 \
    nohup "$PY" agent.py start >"$LOGS/worker-local.log" 2>&1 &

  cd "$ROOT/web"
  AGENT_NAME=hotel-local SITE_TAGLINE="Local models on a Mac · 本機模型" \
    nohup "${PNPM[@]}" start -p 3100 >"$LOGS/web-3100.log" 2>&1 &
  echo "started; logs in $LOGS"
}

stop() {
  pkill -f "agent.py start" || true
  # next renames its process to "next-server", so stop the web servers by port.
  for p in 3100; do
    lsof -nP -tiTCP:"$p" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  done
  echo "stopped"
}

status() {
  for p in 3100 8081; do
    printf "port %-5s " "$p"
    lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && echo "listening" || echo "-"
  done
  grep -h "registered worker" "$LOGS"/worker-*.log 2>/dev/null | grep -o '"agent_name": "[^"]*"' || true
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac

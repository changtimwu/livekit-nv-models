#!/bin/bash
# Run the two public web demos on this Mac (see web/README-hotel.md):
#   hotelbooking.wormhole.work -> web :3100 -> agent "hotel-local"      (local MLX models, .env.local)
#   hotel-tw.wormhole.work     -> web :3101 -> agent "hotel-cloud-zhtw" (LiveKit Inference, zh-tw)
# The Cloudflare Tunnel (cloudflared system service) maps the hostnames to the ports.
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
  # Cloud Taiwan-Mandarin agent: env vars override .env.local (dotenv never overrides).
  AGENT_NAME=hotel-cloud-zhtw AGENT_IDLE_PROCESSES=1 AGENT_HTTP_PORT=8082 \
    AGENT_LANGUAGE=zh-tw LLM_BACKEND=cloud TTS_BACKEND=cloud STT_BACKEND=cloud \
    nohup "$PY" agent.py start >"$LOGS/worker-cloud-zhtw.log" 2>&1 &

  cd "$ROOT/web"
  AGENT_NAME=hotel-local SITE_TAGLINE="Local models on a Mac · 本機模型" \
    nohup "${PNPM[@]}" start -p 3100 >"$LOGS/web-3100.log" 2>&1 &
  AGENT_NAME=hotel-cloud-zhtw SITE_TAGLINE="台灣華語 · 雲端模型 (LiveKit Inference)" \
    nohup "${PNPM[@]}" start -p 3101 >"$LOGS/web-3101.log" 2>&1 &
  echo "started; logs in $LOGS"
}

stop() {
  pkill -f "agent.py start" || true
  # next renames its process to "next-server", so stop the web servers by port.
  for p in 3100 3101; do
    lsof -nP -tiTCP:"$p" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  done
  echo "stopped"
}

status() {
  for p in 3100 3101 8081 8082; do
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

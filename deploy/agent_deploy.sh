#!/bin/bash
# Build + deploy an app's agent to LiveKit Cloud (issues #16, #20).
#   usage: deploy/agent_deploy.sh hotel_receptionist|bendon_ordering [create]
# LiveKit Cloud only sees the app folder, so the shared voiceshared/ package is copied into it
# for the build and removed afterwards. Secrets always come from the app's .env.cloudagent -
# never let lk fall back to .env.local (it holds local-backend settings and LiveKit creds).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:?usage: $0 <app> [create]}"
MODE="${2:-deploy}"
cd "$ROOT/$APP"
[ -f .env.cloudagent ] || { echo "missing $APP/.env.cloudagent" >&2; exit 1; }
rm -rf voiceshared && cp -R "$ROOT/voiceshared" voiceshared && rm -rf voiceshared/__pycache__
trap 'rm -rf "$ROOT/$APP/voiceshared"' EXIT
set -a; . ./.env.local; set +a            # LIVEKIT_* for the lk CLI only
unset AGENT_NAME AGENT_LANGUAGE LLM_BACKEND TTS_BACKEND STT_BACKEND
if [ "$MODE" = create ]; then
  lk agent create --yes --region us-east --secrets-file .env.cloudagent . </dev/null
else
  lk agent deploy --yes --secrets-file .env.cloudagent . </dev/null
fi

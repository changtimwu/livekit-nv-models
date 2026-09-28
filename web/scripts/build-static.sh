#!/bin/bash
# Build the UI as static files for the Cloudflare Worker (issue #16) -> web/out-cf/.
# Static export can't include route handlers or middleware, so build from a temporary copy
# without them (the Worker in cloudflare/worker.ts implements login, token and page gating).
# usage: [OUT_DIR=out-cf] SITE_TAGLINE="..." [NEXT_PUBLIC_*=...] scripts/build-static.sh
#   hotel-tw: SITE_TAGLINE="台灣華語 · 雲端模型 (LiveKit Inference)" scripts/build-static.sh
#   bendon:   scripts/build-bendon.sh
set -euo pipefail
WEB="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-out-cf}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
rsync -a --exclude node_modules --exclude .next --exclude "out-cf*" --exclude .wrangler "$WEB/" "$TMP/"
ln -s "$WEB/node_modules" "$TMP/node_modules"
rm -rf "$TMP/app/api" "$TMP/middleware.ts"
sed -i '' "/^export const dynamic = 'force-dynamic';$/d" "$TMP/app/page.tsx"
(cd "$TMP" && STATIC_EXPORT=1 npx -y pnpm@9.15.9 exec next build)
rm -rf "$WEB/$OUT_DIR" && cp -R "$TMP/out" "$WEB/$OUT_DIR"
echo "static UI -> $WEB/$OUT_DIR"

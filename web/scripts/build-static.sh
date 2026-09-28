#!/bin/bash
# Build the UI as static files for the Cloudflare Worker (issue #16) -> web/out-cf/.
# Static export can't include route handlers or middleware, so build from a temporary copy
# without them (the Worker in cloudflare/worker.ts implements login, token and page gating).
# usage: SITE_TAGLINE="..." scripts/build-static.sh
set -euo pipefail
WEB="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
rsync -a --exclude node_modules --exclude .next --exclude out-cf --exclude .wrangler "$WEB/" "$TMP/"
ln -s "$WEB/node_modules" "$TMP/node_modules"
rm -rf "$TMP/app/api" "$TMP/middleware.ts"
sed -i '' "/^export const dynamic = 'force-dynamic';$/d" "$TMP/app/page.tsx"
(cd "$TMP" && STATIC_EXPORT=1 npx -y pnpm@9.15.9 exec next build)
rm -rf "$WEB/out-cf" && cp -R "$TMP/out" "$WEB/out-cf"
echo "static UI -> $WEB/out-cf"

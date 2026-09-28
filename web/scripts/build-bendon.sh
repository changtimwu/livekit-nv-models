#!/bin/bash
# Static UI for the 愛比食堂 bendon demo (issue #20) -> web/out-cf-bendon/ (wrangler.bendon.jsonc).
set -euo pipefail
cd "$(dirname "$0")"
OUT_DIR=out-cf-bendon \
NEXT_PUBLIC_SITE_TITLE="愛比食堂" \
NEXT_PUBLIC_SITE_DESCRIPTION="愛比食堂 電話點餐（語音 AI 示範）" \
NEXT_PUBLIC_SITE_HEADING="愛比食堂 · 電話點餐" \
NEXT_PUBLIC_LOGIN_PROMPT="請輸入密碼開始點餐。" \
NEXT_PUBLIC_SITE_FOOTER="粥、飯、炒飯、熱炒都可以點，自取或外送（中正區滿三百五十元）。" \
NEXT_PUBLIC_DISCLAIMER="示範用，不會真的送單。" \
NEXT_PUBLIC_HTML_LANG="zh-Hant-TW" \
NEXT_PUBLIC_ORDER_PANEL=1 \
SITE_TAGLINE="台灣華語語音點餐 · LiveKit" \
  ./build-static.sh

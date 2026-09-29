#!/bin/bash
# Static UI for the bendon ordering demo (issues #20, #22) -> web/out-cf-bendon/ (wrangler.bendon.jsonc).
set -euo pipefail
cd "$(dirname "$0")"
# Store picker options from bendon_ordering/stores/*.json, in the Worker's STORES order.
STORES_JSON="$(python3 - <<'PY'
import json, os
d = os.path.join("..", "..", "bendon_ordering", "stores")
order = ["aibi", "dawudi", "yujia"]
out = []
for slug in order:
    s = json.load(open(os.path.join(d, f"{slug}.json"), encoding="utf-8"))
    out.append({"slug": slug, "name": s["name"], "blurb": s.get("blurb", ""), "delivers": s.get("delivery") is not None})
print(json.dumps(out, ensure_ascii=False))
PY
)"
OUT_DIR=out-cf-bendon \
NEXT_PUBLIC_SITE_TITLE="便當電話點餐" \
NEXT_PUBLIC_SITE_DESCRIPTION="便當電話點餐（語音 AI 店員示範）" \
NEXT_PUBLIC_SITE_HEADING="選一家店，開始電話點餐" \
NEXT_PUBLIC_LOGIN_PROMPT="請輸入密碼開始點餐。" \
NEXT_PUBLIC_SITE_FOOTER="用說的點便當：店員會確認每道菜、合計金額，最後給你訂單編號。" \
NEXT_PUBLIC_DISCLAIMER="這是語音AI店員的模擬服務，不代表真實店家，也不會真的送單。" \
NEXT_PUBLIC_STORES="$STORES_JSON" \
NEXT_PUBLIC_HTML_LANG="zh-Hant-TW" \
NEXT_PUBLIC_ORDER_PANEL=1 \
SITE_TAGLINE="台灣華語語音點餐 · LiveKit" \
  ./build-static.sh

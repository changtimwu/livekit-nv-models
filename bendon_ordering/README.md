# Voice order-taker for bendon shops (愛比食堂, 大無敵烤肉飯, 裕佳精緻燒臘)

A voice agent that answers an incoming call and takes takeout orders in Taiwan Mandarin **for the
store the caller picks** in the web page. Plans: GitHub issues #20 (the app) and #22 (multiple
stores). It reuses the patterns from `../hotel_receptionist/` and the shared code in `../voiceshared/`.

| slug | Store | Menu source | Fulfillment |
|---|---|---|---|
| `aibi` (default) | 愛比食堂 (fictional name) | [dinbendon 300528](https://dinbendon.itsi.xyz/shop/300528), 101 items, 8 categories | pickup + delivery (中正區, ≥ NT$350) |
| `dawudi` | 大無敵烤肉飯 (real name) | [634428](https://dinbendon.itsi.xyz/shop/634428), 31 items | pickup only |
| `yujia` | 裕佳精緻燒臘(內湖店) (real name) | [302354](https://dinbendon.itsi.xyz/shop/302354), 21 items, all with 白飯 / 五穀飯 variants | pickup only |

- **Disclaimer:** every call opens with the store name and **「這是語音AI店員的模擬服務，不代表真實店家」**, and the web page says the same. Orders go nowhere.
- **Pickup only:** stores whose listing gives no delivery rules are pickup only.
- **Stack:** by default `AGENT_LANGUAGE=zh-tw` on LiveKit Inference (Deepgram nova-3 zh-TW → Gemma 4 31B → Cartesia sonic-3.6), with the zh-tw speech workarounds from #18.

## Pieces

| File | What |
|---|---|
| `stores/meta/<slug>.json` | hand-maintained: dinbendon shop id, display name, blurb, delivery rules (`null` = pickup only), signatures, renames, **price fixes** |
| `stores/<slug>.json` | generated snapshot (meta + menu, variants) from `scripts/fetch_store.py` |
| `scripts/fetch_store.py` | fetches and validates menus. **A suspicious price must be fixed explicitly in the meta file:** a variant >3× the item's cheapest, or an item >5× the store median. E.g. 裕佳 lists 叉燒香腸飯 五穀飯 at $1210 (white rice $120), fixed to 120 |
| `agent.py` | `OrderTaker` + tools. **The store comes from the dispatch metadata** `{"store": slug}` (validated by the web Worker), else `BENDON_STORE`, else `aibi` |
| `prompt.py` | per-store instructions (menu by name only, fulfillment rules, variant question) + greeting |
| `menu.py` | `Store` + fuzzy search on characters **and** toneless pinyin (homophones like 滷魚→鱸魚, shorthand like 排骨飯→炸排骨飯, Simplified input, the 魩魚/吻仔魚/刎魚 synonyms) |
| `order.py` | order model. **The LLM never owns money:** prices (incl. variant prices), totals, the store's delivery minimum and area, and pickup-only rules are all enforced here |
| `evals/order_flow.py` | scripted-caller scenarios per store, scored on the final order: 愛比 pickup / delivery minimum + upsell / mid-order changes; 大無敵 pickup; 裕佳 variants + a refused delivery |

**Tools:**
- menu: `find_menu_items`, `list_category`
- order lines: `add_item` (with `variant` when a dish has 白飯 / 五穀飯 etc.), `update_item`, `remove_item`, `review_order`
- fulfillment: `set_pickup`, `set_delivery` (enforces the store's minimum and area; refuses for pickup-only stores)
- contact: `set_contact` (Taiwan phone numbers)
- lifecycle: `confirm_order` (gives an order number and ready time), `cancel_order`

**Live order view:** after every change the agent sends a JSON snapshot on the LiveKit text stream `bendon.order`; the web page's order panel (`web/components/app/order-panel.tsx`) renders it.

## Run

```bash
cd bendon_ordering                     # .env.local: LIVEKIT_* + AGENT_LANGUAGE=zh-tw (see .env.example)
BENDON_STORE=yujia ../.venv/bin/python agent.py console   # talk to one store in the terminal
../.venv/bin/python scripts/fetch_store.py               # refresh store snapshots (add a store: new meta file)
../.venv/bin/python evals/order_flow.py   # scenarios (cloud LLM; costs a little Inference credit)
```

## Public demo: https://bendon.wormhole.work (same password as the other demos)

- **Agent:** LiveKit Cloud agent `CA_nXPWXbF4bjAz` (us-east, `AGENT_NAME=bendon-zhtw`). Deploy with `deploy/agent_deploy.sh bendon_ordering` from the repo root. The script copies `voiceshared/` into this folder for the build and uses `.env.cloudagent` for secrets, never `.env.local`.
- **Web:** Cloudflare Worker `bendon-demo`. From `web/`, run `scripts/build-bendon.sh` (it bakes the store picker from `stores/*.json`), then `npx wrangler deploy -c wrangler.bendon.jsonc`. It's the same Worker code as hotel-tw.
  - **Store selection:** the page sends the picked store as `agentMetadata`. The Worker accepts only slugs in its `STORES` var, ignores any client-sent agent name or extra keys, and writes the dispatch metadata itself.
- **Adding a store:** add `stores/meta/<slug>.json`, run `scripts/fetch_store.py <slug>`, add the slug to `STORES` in `wrangler.bendon.jsonc` and to the order in `web/scripts/build-bendon.sh`, then redeploy the agent and the Worker.

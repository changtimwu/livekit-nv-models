# 愛比食堂 phone order-taker (bendon ordering demo)

A voice agent that answers an incoming call and takes takeout / delivery orders in Taiwan
Mandarin. Plan and decisions: GitHub issue #20. It reuses the patterns proven in
`../hotel_receptionist/` and the shared code in `../voiceshared/`.

- **Shop:** fictional **愛比食堂**, with the menu of a real 中正區 shop (101 items, 8 categories). The snapshot is in `menu.json`, from https://dinbendon.itsi.xyz/shop/300528; its source listing is dated 2023/08/22. The web page says 「示範用，不會真的送單」 and the agent says so if asked. Orders go nowhere.
- **Stack:** by default `AGENT_LANGUAGE=zh-tw` on LiveKit Inference: Deepgram nova-3 zh-TW → Gemma 4 31B → Cartesia sonic-3.6, with the zh-tw speech workarounds from #18. The `*_BACKEND=local` toggles work as in the hotel app.

## Pieces

| File | What |
|---|---|
| `agent.py` | `OrderTaker` agent + tools; fixed greeting; publishes the order to the web page |
| `prompt.py` | English instructions, Taiwan-Mandarin speech, the menu by name only (prices only from tools) |
| `menu.py` | menu loading + fuzzy search on characters **and** toneless pinyin (homophones like 滷魚→鱸魚, shorthand like 排骨飯→炸排骨飯, Simplified input, the 魩魚/吻仔魚/刎魚 synonyms) |
| `order.py` | order model. **The LLM never owns money:** prices, totals, the NT$350 delivery minimum and the 中正區 area check are all computed here |
| `evals/order_flow.py` | scripted-caller scenarios scored on the final order (pickup, delivery under the minimum + upsell, mid-order changes) |
| `scripts/fetch_menu.py` | regenerates `menu.json` (丼飯 items are stored as `牛肉丼飯` etc.) |

**Tools:**
- menu: `find_menu_items`, `list_category`
- order lines: `add_item`, `update_item`, `remove_item`, `review_order`
- fulfillment: `set_pickup`, `set_delivery` (enforces the minimum and the area)
- contact: `set_contact` (Taiwan phone numbers)
- lifecycle: `confirm_order` (gives an order number and ready time), `cancel_order`

**Live order view:** after every change the agent sends a JSON snapshot on the LiveKit text stream `bendon.order`; the web page's order panel (`web/components/app/order-panel.tsx`) renders it.

## Run

```bash
cd bendon_ordering                     # .env.local: LIVEKIT_* + AGENT_LANGUAGE=zh-tw (see .env.example)
../.venv/bin/python agent.py console   # talk in the terminal
../.venv/bin/python evals/order_flow.py   # scenarios (cloud LLM; costs a little Inference credit)
```

## Public demo: https://bendon.wormhole.work (same password as the other demos)

- **Agent:** LiveKit Cloud agent `CA_nXPWXbF4bjAz` (us-east, `AGENT_NAME=bendon-zhtw`). Deploy with `deploy/agent_deploy.sh bendon_ordering` from the repo root. The script copies `voiceshared/` into this folder for the build and uses `.env.cloudagent` for secrets, never `.env.local`.
- **Web:** Cloudflare Worker `bendon-demo`. From `web/`, run `scripts/build-bendon.sh`, then `npx wrangler deploy -c wrangler.bendon.jsonc`. It's the same Worker code as hotel-tw.

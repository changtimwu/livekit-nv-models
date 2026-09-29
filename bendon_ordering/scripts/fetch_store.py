"""Snapshot a store's menu from dinbendon into bendon_ordering/stores/<slug>.json (issue #22).

The hand-maintained stores/meta/<slug>.json supplies the dinbendon shop id and everything the
page doesn't (display name, fulfillment rules, signature dishes, renames, price fixes). The
menu is validated: a suspicious price (a variant >3x the item's cheapest, or an item >5x the
store median) must be fixed explicitly in "price_fixes" - the agent can never charge it.

usage: python bendon_ordering/scripts/fetch_store.py [slug ...]   (default: every meta file)
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import statistics
import sys
import urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_DIR = os.path.join(ROOT, "stores", "meta")
SOURCE = "https://dinbendon.itsi.xyz/shop/{id}"
NO_CATEGORY = "___UNDEFINED___"


class MenuParser(HTMLParser):
    """section.cat > h3 (category) + li > span.pname, span.price or span.var (label + price)."""

    def __init__(self) -> None:
        super().__init__()
        self.categories: list[dict] = []
        self.meta: dict[str, str] = {}
        self._field: str | None = None
        self._buf = ""
        self._dt = ""
        self._item: dict | None = None
        self._var_label: str | None = None

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag == "h3":
            self._field, self._buf = "cat", ""
        elif tag == "span" and cls == "pname":
            self._item = {"name": "", "prices": []}
            self._field, self._buf = "pname", ""
        elif tag == "span" and cls == "var":
            self._field, self._buf = "var", ""
        elif tag == "span" and cls == "price":
            if self._field == "var":
                self._var_label = self._buf.strip()
            self._field, self._buf = "price", ""
        elif tag in ("dt", "dd"):
            self._field, self._buf = tag, ""

    def handle_data(self, data):
        if self._field:
            self._buf += data

    def handle_endtag(self, tag):
        text = self._buf.strip()
        if self._field == "cat" and tag == "h3":
            self.categories.append({"name": text, "items": []})
        elif self._field == "pname" and tag == "span":
            self._item["name"] = text
        elif self._field == "price" and tag == "span":
            self._item["prices"].append((self._var_label, int(re.sub(r"\D", "", text))))
            self._var_label = None
        elif self._field == "dt" and tag == "dt":
            self._dt = text
        elif self._field == "dd" and tag == "dd":
            self.meta[self._dt] = " ".join(text.split())
        if tag == "li" and self._item is not None:
            self.categories[-1]["items"].append(self._item)
            self._item = None
        if tag in ("h3", "dt", "dd") or (tag == "span" and self._field in ("pname", "price")):
            self._field = None


def build(meta: dict) -> dict:
    url = SOURCE.format(id=meta["source_shop_id"])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (menu snapshot)"})
    p = MenuParser()
    p.feed(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))

    fixes = dict(meta.get("price_fixes", {}))
    items, problems = [], []
    for ci, cat in enumerate(p.categories, 1):
        category = "" if cat["name"] == NO_CATEGORY else cat["name"]
        for ii, it in enumerate(cat["items"], 1):
            name = it["name"]
            tmpl = meta.get("rename", {}).get(f"category:{cat['name']}")
            if tmpl and "丼" not in name:
                name = tmpl.format(name=name)  # e.g. 愛比食堂's bare 丼飯 names (牛肉 -> 牛肉丼飯)
            prices = []
            for label, price in it["prices"]:
                key = f"{it['name']}|{label}" if label else it["name"]
                if key in fixes:
                    fix = fixes.pop(key)
                    if price != fix["from"]:
                        problems.append(f"{key}: fix expects {fix['from']} but source now says {price}")
                    price = fix["to"]
                prices.append((label, price))
            if not prices:
                problems.append(f"{name}: no price")
                continue
            item = {"id": f"c{ci:02d}i{ii:02d}", "category": category, "name": name,
                    "price": min(pr for _, pr in prices)}
            if any(label for label, _ in prices):
                item["variants"] = [{"name": label, "price": pr} for label, pr in prices]
                for label, pr in prices:
                    if pr > 3 * item["price"]:
                        problems.append(f"{name}|{label}: {pr} is >3x its cheapest variant {item['price']}")
            elif len(prices) > 1:
                problems.append(f"{name}: several unlabeled prices {prices}")
            items.append(item)
    median = statistics.median(i["price"] for i in items)
    problems += [f"{i['name']}: {i['price']} is >5x the store median {median}"
                 for i in items if i["price"] > 5 * median]
    problems += [f"unused price fix {k!r}" for k in fixes]
    if problems:
        raise SystemExit(f"{meta['slug']}: fix these in stores/meta/{meta['slug']}.json:\n  "
                         + "\n  ".join(problems))

    return {
        **{k: v for k, v in meta.items() if k not in ("rename", "price_fixes")},
        "source": url,
        "source_updated": p.meta.get("更新", "").split("·")[0].strip(),
        "source_notice": p.meta.get("公告", ""),
        "address": p.meta.get("地址", "").replace(" 地圖", ""),
        "snapshot_date": dt.date.today().isoformat(),
        "price_fixes_applied": meta.get("price_fixes", {}),
        "categories": list(dict.fromkeys(i["category"] for i in items if i["category"])),
        "items": items,
    }


def main() -> None:
    slugs = sys.argv[1:] or sorted(
        os.path.basename(f)[:-5] for f in glob.glob(os.path.join(META_DIR, "*.json")))
    for slug in slugs:
        with open(os.path.join(META_DIR, f"{slug}.json"), encoding="utf-8") as f:
            store = build(json.load(f))
        out = os.path.join(ROOT, "stores", f"{slug}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
        n_var = sum(1 for i in store["items"] if "variants" in i)
        print(f"{slug}: {store['name']} - {len(store['items'])} items ({n_var} with variants), "
              f"{len(store['categories'])} categories -> stores/{slug}.json")


if __name__ == "__main__":
    main()

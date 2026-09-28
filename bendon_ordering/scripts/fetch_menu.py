"""Snapshot the menu used by the bendon ordering demo into bendon_ordering/menu.json.

Source: https://dinbendon.itsi.xyz/shop/300528 (public dinbendon.net data). The demo presents
the menu as the fictional 「愛比食堂」 (issue #20); nothing is fetched at call time.

usage: python bendon_ordering/scripts/fetch_menu.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.request
from html.parser import HTMLParser

SOURCE = "https://dinbendon.itsi.xyz/shop/300528"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "menu.json")


class MenuParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.categories: list[dict] = []
        self.notice = ""
        self.updated = ""
        self._field: str | None = None  # which element's text we're collecting
        self._buf = ""
        self._dt = ""
        self._item: dict | None = None

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag == "h3":
            self._field, self._buf = "cat", ""
        elif tag == "span" and cls == "pname":
            self._item = {"name": "", "prices": []}
            self._field, self._buf = "pname", ""
        elif tag == "span" and cls == "price":
            self._field, self._buf = "price", ""
        elif tag == "dt":
            self._field, self._buf = "dt", ""
        elif tag == "dd":
            self._field, self._buf = "dd", ""

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
            self._item["prices"].append(int(re.sub(r"\D", "", text)))
        elif self._field == "dt" and tag == "dt":
            self._dt = text
        elif self._field == "dd" and tag == "dd":
            if self._dt == "公告":
                self.notice = text
            elif self._dt == "更新":
                self.updated = text.split("·")[0].strip()
        if tag == "li" and self._item is not None:
            self.categories[-1]["items"].append(self._item)
            self._item = None
        if tag in ("h3", "span", "dt", "dd"):
            self._field = None


def main() -> None:
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0 (menu snapshot)"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    p = MenuParser()
    p.feed(html)
    items = []
    for ci, cat in enumerate(p.categories, 1):
        for ii, it in enumerate(cat["items"], 1):
            if len(it["prices"]) != 1:
                raise SystemExit(f"unexpected price list for {it['name']}: {it['prices']}")
            name = it["name"]
            if cat["name"] == "丼飯" and "丼" not in name:
                name += "丼飯"  # the page lists them bare (牛肉, 雞肉...), ambiguous by voice
            items.append({"id": f"c{ci:02d}i{ii:02d}", "category": cat["name"],
                          "name": name, "price": it["prices"][0]})
    menu = {
        "source": SOURCE,
        "source_updated": p.updated,
        "snapshot_date": dt.date.today().isoformat(),
        "source_notice": p.notice,
        "categories": [c["name"] for c in p.categories],
        "items": items,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(menu, f, ensure_ascii=False, indent=1)
    print(f"{len(items)} items in {len(p.categories)} categories -> {OUT}")


if __name__ == "__main__":
    main()

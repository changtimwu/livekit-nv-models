"""Store data (stores/<slug>.json snapshots) and fuzzy, homophone-tolerant item search.

Callers' words arrive through STT, so a dish can come in misrecognized (滷魚粥 for 鱸魚粥),
in shorthand (排骨飯 for 炸排骨飯) or in Simplified characters. Matching therefore scores each
item on characters *and* toneless pinyin, which is script-agnostic and catches homophones.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache

from pypinyin import lazy_pinyin

_STORES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stores")
DEFAULT_STORE = "aibi"

# Quantity / packaging words a caller may attach to a dish name ("兩個排骨飯", "粥一碗").
_NOISE = re.compile(r"[\s，。、,.!?！？]|[一二兩三四五六七八九十\d]+(個|份|碗|盒|杯|盤)|(個|份|碗|盒|杯|盤)$")


@dataclass(frozen=True)
class Variant:
    name: str  # e.g. 白飯 / 五穀飯
    price: int


@dataclass(frozen=True)
class OptionChoice:
    name: str
    price: int  # added to the item price, e.g. 加菜 +40


@dataclass(frozen=True)
class OptionGroup:
    """A per-store choice applied to some items, e.g. 飯量 正常/飯少/不要飯 (#24)."""
    id: str
    name: str
    choices: tuple[OptionChoice, ...]
    default: str | None  # None = the caller must choose (the agent asks)

    def choice(self, name: str) -> OptionChoice | None:
        return next((c for c in self.choices if c.name == name), None)

    def describe(self) -> str:
        cs = "/".join(c.name + (f"(+{c.price})" if c.price else "") for c in self.choices)
        return f"{self.name} {cs}" + (f" [default {self.default}]" if self.default else " [ask]")


@dataclass(frozen=True)
class MenuItem:
    id: str
    category: str
    name: str
    price: int  # cheapest variant when there are variants
    variants: tuple[Variant, ...] = ()
    kcal: int | None = None
    option_groups: tuple[OptionGroup, ...] = ()

    def variant(self, name: str) -> Variant | None:
        want = name.strip()
        return next((v for v in self.variants if v.name == want or want in v.name), None)

    def describe(self) -> str:
        if self.variants:
            vs = " / ".join(f"{v.name} {v.price}" for v in self.variants)
            out = f"[{self.id}] {self.name} (variants: {vs})"
        else:
            out = f"[{self.id}] {self.name} {self.price}"
        extra = []
        if self.kcal is not None:
            extra.append(f"{self.kcal} kcal")
        if self.option_groups:
            extra.append("options: " + "; ".join(g.describe() for g in self.option_groups))
        return out + (f" ({'; '.join(extra)})" if extra else "")


class Store:
    """One shop: meta (name, fulfillment rules, signatures...) + its menu."""

    def __init__(self, data: dict) -> None:
        self.slug: str = data["slug"]
        self.name: str = data["name"]
        self.spoken_name: str = data.get("spoken_name") or data["name"]
        self.blurb: str = data.get("blurb", "")
        self.description: str = data.get("description", "")
        self.address: str = data.get("address", "")
        self.delivery: dict | None = data.get("delivery")  # None = pickup only
        self.delivery_note: str = data.get("delivery_note", "")  # e.g. 外送請透過 Uber Eats
        self.signatures: list[str] = data.get("signatures", [])
        self.pickup_minutes: int = data.get("pickup_minutes", 20)
        self.delivery_minutes: int = data.get("delivery_minutes", 40)
        self.categories: list[str] = data.get("categories", [])
        self.option_groups: dict[str, OptionGroup] = {
            g["id"]: OptionGroup(g["id"], g["name"],
                                 tuple(OptionChoice(c["name"], c.get("price", 0)) for c in g["choices"]),
                                 g.get("default"))
            for g in data.get("option_groups", [])
        }
        self.items: list[MenuItem] = [
            MenuItem(i["id"], i["category"], i["name"], i["price"],
                     tuple(Variant(v["name"], v["price"]) for v in i.get("variants", [])),
                     i.get("kcal"),
                     tuple(self.option_groups[g] for g in i.get("options", [])))
            for i in data["items"]
        ]
        self._by_id = {it.id: it for it in self.items}

    @property
    def delivers(self) -> bool:
        return self.delivery is not None

    def get(self, item_id: str) -> MenuItem | None:
        return self._by_id.get(item_id)

    def search(self, query: str, limit: int = 5, threshold: float = 0.45) -> list[tuple[MenuItem, float]]:
        scored = sorted(((it, score(query, it)) for it in self.items), key=lambda t: -t[1])
        best = [(it, sc) for it, sc in scored[:limit] if sc >= threshold]
        # If there's a clear exact/near-exact winner, don't bury it among weak alternatives.
        if best and best[0][1] >= 0.95:
            best = [b for b in best if b[1] >= 0.8]
        return best


def store_slugs() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(_STORES_DIR) if f.endswith(".json"))


@lru_cache(maxsize=None)
def load_store(slug: str) -> Store:
    if slug not in store_slugs():
        raise ValueError(f"unknown store {slug!r}; known: {store_slugs()}")
    with open(os.path.join(_STORES_DIR, f"{slug}.json"), encoding="utf-8") as f:
        return Store(json.load(f))


def _norm(text: str) -> str:
    return _NOISE.sub("", text)


@lru_cache(maxsize=4096)
def _py(text: str) -> tuple[str, ...]:
    return tuple(lazy_pinyin(text))


def _lcs(a: tuple | str, b: tuple | str) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


# Same ingredient, different spellings on the menu or from callers (the menu itself has
# 魩魚, 吻仔魚 and the typo 刎魚).
_SYNONYMS = [("魩魚", "吻仔魚", "刎魚", "吻魚")]


def _variants(query: str) -> set[str]:
    out = {query, _norm(query)}
    for group in _SYNONYMS:
        for v in list(out):
            for a in group:
                if a in v:
                    out.update(v.replace(a, b) for b in group)
    return {v for v in out if v}


def score(query: str, item: MenuItem) -> float:
    # Best over raw / quantity-stripped / synonym variants (三杯雞 must not lose "三杯").
    return max(_score_one(v, item) for v in _variants(query))


def _score_one(q: str, item: MenuItem) -> float:
    n = item.name
    if not q:
        return 0.0
    if q == n:
        return 1.0
    if q in n or n in q:
        # substring either way: 排骨飯 in 炸排骨飯, or the caller added words
        return 0.75 + 0.2 * min(len(q), len(n)) / max(len(q), len(n))
    # in-order overlap on characters and on pinyin (homophones, Simplified input)
    chars = _lcs(q, n) / max(len(q), len(n))
    pq, pn = _py(q), _py(n)
    pinyin = _lcs(pq, pn) / max(len(pq), len(pn))
    return max(chars, pinyin) * 0.9

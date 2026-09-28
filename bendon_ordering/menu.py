"""Menu data (menu.json snapshot) and fuzzy, homophone-tolerant item search.

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

_MENU_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu.json")

# Quantity / packaging words a caller may attach to a dish name ("兩個排骨飯", "粥一碗").
_NOISE = re.compile(r"[\s，。、,.!?！？]|[一二兩三四五六七八九十\d]+(個|份|碗|盒|杯|盤)|(個|份|碗|盒|杯|盤)$")


@dataclass(frozen=True)
class MenuItem:
    id: str
    category: str
    name: str
    price: int


@lru_cache(maxsize=1)
def load_menu() -> dict:
    with open(_MENU_PATH, encoding="utf-8") as f:
        data = json.load(f)
    data["by_id"] = {i["id"]: MenuItem(**i) for i in data["items"]}
    return data


def items() -> list[MenuItem]:
    return list(load_menu()["by_id"].values())


def categories() -> list[str]:
    return load_menu()["categories"]


def get(item_id: str) -> MenuItem | None:
    return load_menu()["by_id"].get(item_id)


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


def search(query: str, limit: int = 5, threshold: float = 0.45) -> list[tuple[MenuItem, float]]:
    scored = sorted(((it, score(query, it)) for it in items()), key=lambda t: -t[1])
    best = [(it, s) for it, s in scored[:limit] if s >= threshold]
    # If there's a clear exact/near-exact winner, don't bury it among weak alternatives.
    if best and best[0][1] >= 0.95:
        best = [b for b in best if b[1] >= 0.8]
    return best

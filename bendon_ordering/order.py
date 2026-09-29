"""The caller's order: lines, fulfillment, contact, and server-side money.

Invariant carried over from the hotel app: **the LLM never owns money**. Prices come from the
menu snapshot, subtotals and totals are computed here, and the delivery minimum is enforced
here - tool results are the only place the model learns a number it may say.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from menu import Store

# Fulfillment rules come from the store (stores/meta/<slug>.json). Stores whose source lists no
# delivery rules are pickup only (#22). Delivery areas are checked by address hints - there's
# no geocoding, so e.g. 愛比食堂 accepts addresses naming 中正區.


class OrderError(Exception):
    """A request the order can't accept; the message is safe to relay to the caller."""


@dataclass
class Line:
    item_id: str
    name: str
    unit_price: int
    quantity: int
    note: str = ""
    variant: str = ""  # e.g. 白飯 / 五穀飯

    @property
    def label(self) -> str:
        return f"{self.name}（{self.variant}）" if self.variant else self.name

    @property
    def amount(self) -> int:
        return self.unit_price * self.quantity


@dataclass
class Order:
    store: Store
    lines: list[Line] = field(default_factory=list)
    mode: str | None = None  # "pickup" | "delivery"
    address: str = ""
    time: str = ""
    name: str = ""
    phone: str = ""
    status: str = "open"  # open | confirmed | cancelled
    order_no: str = ""

    # ---- items -------------------------------------------------------------------------
    def _find(self, item_id: str, variant: str | None = None) -> Line | None:
        return next((ln for ln in self.lines
                     if ln.item_id == item_id and (variant is None or ln.variant == variant)), None)

    def _require_open(self) -> None:
        if self.status != "open":
            raise OrderError(f"order is already {self.status}")

    def add(self, item_id: str, quantity: int, note: str = "", variant: str = "") -> Line:
        self._require_open()
        item = self.store.get(item_id)
        if item is None:
            raise OrderError(f"unknown item id {item_id!r} - look it up with find_menu_items first")
        if not 1 <= quantity <= 50:
            raise OrderError("quantity must be between 1 and 50")
        price, chosen = item.price, ""
        if item.variants:
            v = item.variant(variant) if variant else None
            if v is None:
                opts = " / ".join(x.name for x in item.variants)
                raise OrderError(f"{item.name} needs a choice of {opts} - ask the caller which one")
            price, chosen = v.price, v.name
        line = self._find(item_id, chosen)
        if line and line.note == note.strip():
            line.quantity += quantity
            return line
        line = Line(item.id, item.name, price, quantity, note.strip(), chosen)
        self.lines.append(line)
        return line

    def update(self, item_id: str, quantity: int | None, note: str | None,
               variant: str | None = None) -> Line | None:
        self._require_open()
        line = self._find(item_id, variant or None)
        if line is None:
            raise OrderError(f"{item_id!r} is not in the order")
        if quantity is not None:
            if quantity <= 0:
                self.lines.remove(line)
                return None
            if quantity > 50:
                raise OrderError("quantity must be between 1 and 50")
            line.quantity = quantity
        if note is not None:
            line.note = note.strip()
        return line

    def remove(self, item_id: str, variant: str | None = None) -> None:
        self.update(item_id, 0, None, variant)

    # ---- money -------------------------------------------------------------------------
    @property
    def subtotal(self) -> int:
        return sum(ln.amount for ln in self.lines)

    @property
    def total(self) -> int:
        return self.subtotal  # no delivery fee or tax in the source data

    # ---- fulfillment / contact --------------------------------------------------------
    def set_pickup(self, time: str) -> None:
        self._require_open()
        self.mode, self.address, self.time = "pickup", "", time.strip() or "盡快"

    def set_delivery(self, address: str, time: str) -> None:
        self._require_open()
        rules = self.store.delivery
        if rules is None:
            raise OrderError("this store is pickup only (自取) - no delivery; offer pickup")
        minimum = rules.get("minimum", 0)
        if self.subtotal < minimum:
            raise OrderError(
                f"delivery needs a subtotal of at least {minimum}; the order is "
                f"{self.subtotal}, {minimum - self.subtotal} short - offer to add items "
                "or switch to pickup"
            )
        hints = rules.get("area_hints", [])
        if hints and not any(h in address for h in hints):
            raise OrderError(
                f"the shop only delivers to {rules.get('area_text', '、'.join(hints))}; "
                "ask for an address there or offer pickup"
            )
        self.mode, self.address, self.time = "delivery", address.strip(), time.strip() or "盡快"

    def set_contact(self, name: str, phone: str) -> None:
        self._require_open()
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("886"):
            digits = "0" + digits[3:]
        if not re.fullmatch(r"09\d{8}|0[2-8]\d{7,8}", digits):
            raise OrderError(
                f"{phone!r} doesn't look like a Taiwan phone number (mobile 09xx-xxx-xxx or a "
                "landline with area code) - ask the caller to repeat it"
            )
        if not name.strip():
            raise OrderError("a name for the order is required")
        self.name, self.phone = name.strip(), digits

    # ---- lifecycle ---------------------------------------------------------------------
    def missing(self) -> list[str]:
        out = []
        if not self.lines:
            out.append("items")
        if self.mode is None:
            out.append("pickup_or_delivery")
        if not self.phone:
            out.append("name_and_phone")
        return out

    def confirm(self) -> None:
        self._require_open()
        if self.missing():
            raise OrderError(f"can't confirm yet, still missing: {', '.join(self.missing())}")
        minimum = (self.store.delivery or {}).get("minimum", 0)
        if self.mode == "delivery" and self.subtotal < minimum:
            raise OrderError(f"delivery minimum is {minimum}; the order is {self.subtotal}")
        self.status = "confirmed"
        self.order_no = "A" + "".join(random.choice("0123456789") for _ in range(3))

    def cancel(self) -> None:
        self._require_open()
        self.status = "cancelled"

    @property
    def ready_minutes(self) -> int:
        return self.store.delivery_minutes if self.mode == "delivery" else self.store.pickup_minutes

    # ---- views -------------------------------------------------------------------------
    def summary(self) -> str:
        """Compact text for tool results (the model reads this, then speaks)."""
        if not self.lines:
            body = "order is empty"
        else:
            body = "; ".join(
                f"[{ln.item_id}] {ln.label} x{ln.quantity} = {ln.amount}" + (f" (note: {ln.note})" if ln.note else "")
                for ln in self.lines
            )
        parts = [body, f"subtotal {self.subtotal}"]
        if self.mode == "pickup":
            parts.append(f"pickup at {self.time}")
        elif self.mode == "delivery":
            parts.append(f"delivery to {self.address} at {self.time}")
        if self.phone:
            parts.append(f"contact {self.name} {self.phone}")
        if self.missing() and self.status == "open":
            parts.append(f"still missing: {', '.join(self.missing())}")
        return " | ".join(parts)

    def snapshot(self) -> dict:
        """JSON for the live order view in the web page."""
        return {
            "store": self.store.name,
            "delivers": self.store.delivers,
            "status": self.status,
            "order_no": self.order_no,
            "lines": [
                {"name": ln.label, "quantity": ln.quantity, "unit_price": ln.unit_price,
                 "amount": ln.amount, "note": ln.note}
                for ln in self.lines
            ],
            "subtotal": self.subtotal,
            "total": self.total,
            "mode": self.mode,
            "address": self.address,
            "time": self.time,
            "name": self.name,
            "phone_masked": (self.phone[:4] + "…" + self.phone[-3:]) if self.phone else "",
            "delivery_minimum": (self.store.delivery or {}).get("minimum", 0),
        }

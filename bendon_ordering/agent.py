"""愛比食堂 phone order-taker (issue #20): a voice agent that takes bendon / takeout orders.

Run from this directory, like the hotel app:
    python agent.py console     # talk in the terminal
    python agent.py dev|start   # connect as a worker (web demo dispatches AGENT_NAME)

Defaults to Taiwan Mandarin (AGENT_LANGUAGE=zh-tw) on the cloud stack; the shared
*_BACKEND toggles (voiceshared.backends) switch any slot to local MLX. The web page gets a
live view of the order on the "bendon.order" text stream.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(_HERE)
if not os.path.isdir(os.path.join(_HERE, "voiceshared")):
    # Local runs: the shared package lives at the repo root. LiveKit Cloud images get a
    # copy inside the app folder instead (deploy/agent_deploy.sh).
    sys.path.append(os.path.dirname(_HERE))

from dotenv import load_dotenv

load_dotenv(".env.local")
os.environ.setdefault("AGENT_LANGUAGE", "zh-tw")  # this app is Taiwan-Mandarin-first

import menu  # noqa: E402
from order import Order, OrderError  # noqa: E402
from prompt import GREETING, build_instructions  # noqa: E402
from voiceshared.backends import (  # noqa: E402
    agent_name,
    agent_server,
    build_llm,
    build_stt,
    build_tts,
    session_conn_options,
)

from livekit import rtc  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    ToolError,
    cli,
    function_tool,
    inference,
)

logger = logging.getLogger("bendon-ordering")

ORDER_TOPIC = "bendon.order"


@dataclass
class Userdata:
    room: rtc.Room | None = None
    order: Order = field(default_factory=Order)

    async def publish(self) -> None:
        """Send the order snapshot to the web page's live order view."""
        if self.room is None:
            return
        try:
            await self.room.local_participant.send_text(
                json.dumps(self.order.snapshot(), ensure_ascii=False), topic=ORDER_TOPIC
            )
        except Exception:  # never let the UI feed break the call
            logger.exception("failed to publish order snapshot")


def _raise(e: OrderError) -> None:
    raise ToolError(str(e)) from e


class OrderTaker(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=build_instructions())

    async def on_enter(self) -> None:
        await self.session.userdata.publish()
        # A fixed greeting: instant, and it doesn't wait on the LLM (#11).
        await self.session.say(GREETING)

    @function_tool()
    async def find_menu_items(self, ctx: RunContext[Userdata], query: str) -> str:
        """Look up menu items matching what the caller said (tolerates misheard or
        shorthand dish names). Always call this before add_item.

        Args:
            query: The dish as the caller said it, e.g. "排骨飯" or "皮蛋粥".
        """
        hits = menu.search(query)
        if not hits:
            return f"no menu item matches {query!r}"
        return "matches: " + "; ".join(f"[{it.id}] {it.name} {it.price} ({it.category})" for it, _ in hits)

    @function_tool()
    async def list_category(self, ctx: RunContext[Userdata], category: str) -> str:
        """List the dishes (with prices) in one menu category.

        Args:
            category: One of the menu categories, e.g. "粥品" or "炒飯".
        """
        rows = [it for it in menu.items() if it.category == category.strip()]
        if not rows:
            return f"no category {category!r}; categories: {'、'.join(menu.categories())}"
        return "; ".join(f"[{it.id}] {it.name} {it.price}" for it in rows)

    @function_tool()
    async def add_item(
        self, ctx: RunContext[Userdata], item_id: str, quantity: int = 1, note: str = ""
    ) -> str:
        """Add a dish to the order.

        Args:
            item_id: The id from find_menu_items / list_category, e.g. "c06i03".
            quantity: How many; a dish named without a count means 1.
            note: Special requests for this dish, e.g. "飯少、不要蔥". Empty if none.
        """
        try:
            line = ctx.userdata.order.add(item_id, quantity, note)
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return f"added {line.name} (now x{line.quantity}) | {ctx.userdata.order.summary()}"

    @function_tool()
    async def update_item(
        self,
        ctx: RunContext[Userdata],
        item_id: str,
        quantity: int | None = None,
        note: str | None = None,
    ) -> str:
        """Change the quantity and/or note of a dish already in the order. Quantity 0 removes it.

        Args:
            item_id: The dish's id.
            quantity: The new total quantity, or omit to keep it.
            note: The new note, or omit to keep it.
        """
        try:
            ctx.userdata.order.update(item_id, quantity, note)
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return f"updated | {ctx.userdata.order.summary()}"

    @function_tool()
    async def remove_item(self, ctx: RunContext[Userdata], item_id: str) -> str:
        """Remove a dish from the order.

        Args:
            item_id: The dish's id.
        """
        try:
            ctx.userdata.order.remove(item_id)
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return f"removed | {ctx.userdata.order.summary()}"

    @function_tool()
    async def review_order(self, ctx: RunContext[Userdata]) -> str:
        """Get the current order with server-computed amounts and total, for reading it back."""
        return ctx.userdata.order.summary()

    @function_tool()
    async def set_pickup(self, ctx: RunContext[Userdata], time: str) -> str:
        """The caller will pick the order up at the shop.

        Args:
            time: When, as the caller said it, e.g. "中午十二點半" or "盡快".
        """
        try:
            ctx.userdata.order.set_pickup(time)
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return f"pickup set | {ctx.userdata.order.summary()}"

    @function_tool()
    async def set_delivery(self, ctx: RunContext[Userdata], address: str, time: str) -> str:
        """Deliver the order. The shop delivers only in 中正區 with a subtotal of at least 350.

        Args:
            address: The full delivery address as the caller said it.
            time: When, e.g. "十二點" or "盡快".
        """
        try:
            ctx.userdata.order.set_delivery(address, time)
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return f"delivery set | {ctx.userdata.order.summary()}"

    @function_tool()
    async def set_contact(self, ctx: RunContext[Userdata], name: str, phone: str) -> str:
        """Record the caller's name and Taiwan phone number for the order.

        Args:
            name: How to address the caller, e.g. "王先生" or "吳添".
            phone: The phone number digits as spoken, e.g. "0912345678".
        """
        try:
            ctx.userdata.order.set_contact(name, phone)
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return f"contact set | {ctx.userdata.order.summary()}"

    @function_tool()
    async def confirm_order(self, ctx: RunContext[Userdata]) -> str:
        """Place the order. Only after the caller confirmed the read-back."""
        order = ctx.userdata.order
        try:
            order.confirm()
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return (f"order placed: order number {order.order_no}, total {order.total}, "
                f"ready in about {order.ready_minutes} minutes ({order.mode})")

    @function_tool()
    async def cancel_order(self, ctx: RunContext[Userdata]) -> str:
        """Cancel the whole order (the caller no longer wants it)."""
        try:
            ctx.userdata.order.cancel()
        except OrderError as e:
            _raise(e)
        await ctx.userdata.publish()
        return "order cancelled"


server = agent_server()


@server.rtc_session(agent_name=agent_name())
async def bendon_agent(ctx: JobContext) -> None:
    await ctx.connect()
    userdata = Userdata(room=ctx.room)
    vad = inference.VAD(model="silero")
    session = AgentSession[Userdata](
        userdata=userdata,
        vad=vad,
        stt=build_stt(vad),
        llm=build_llm(),
        tts=build_tts(),
        max_tool_steps=5,
        conn_options=session_conn_options(),
    )
    await session.start(agent=OrderTaker(), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)

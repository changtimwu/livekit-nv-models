"""Scripted-caller evals for the voice order-taker, per store (issues #20, #22).

A keyword-driven caller answers whatever the agent asks (text only, real tools and order
state), and each scenario is scored on the *final order*: dishes, quantities, total,
fulfillment and status. The LLM is whatever the agent would use (cloud by default).

usage (from bendon_ordering/):  python evals/order_flow.py [scenario ...]
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent  # noqa: E402
import menu  # noqa: E402

from livekit.agents import AgentSession  # noqa: E402

SCENARIOS = {
    "pickup": {
        "store": "aibi",
        "items": ["我要兩個排骨飯，一個皮蛋粥。"],
        "mode": "自取。", "time": "十二點半。", "address": "",
        "expect": {"lines": {"炸排骨飯": 2, "皮蛋瘦肉粥": 1}, "total": 300, "mode": "pickup"},
    },
    "delivery_minimum": {
        "store": "aibi",
        # 滷魚粥 = homophone of 鱸魚粥 (205): below the 350 delivery minimum until 三杯雞 (200).
        "items": ["我要一碗滷魚粥，外送。"],
        "mode": "外送。", "time": "盡快。", "address": "台北市中正區寧波西街五號。",
        "upsell": "那再加一個三杯雞。",
        "expect": {"lines": {"鱸魚粥": 1, "三杯雞": 1}, "total": 405, "mode": "delivery"},
    },
    "modify": {
        "store": "aibi",
        "items": ["我要一個蝦仁蛋炒飯，還有一碗番茄蛋花湯。", "炒飯改成兩個。", "湯不要了。"],
        "mode": "自取。", "time": "盡快。", "address": "",
        "expect": {"lines": {"蝦仁蛋炒飯": 2}, "total": 250, "mode": "pickup"},
    },
    "dawudi_pickup": {
        "store": "dawudi",
        "items": ["我要兩個烤肉飯，一個烤雞腿飯。"],
        "mode": "自取。", "time": "十二點。", "address": "",
        "expect": {"lines": {"烤肉飯": 2, "烤雞腿飯": 1}, "total": 350, "mode": "pickup"},
    },
    "yujia_variants": {
        # The 三寶飯 needs a rice choice; the caller also asks for delivery (pickup-only store).
        "store": "yujia",
        "items": ["我要一個玫瑰油雞飯五穀飯，兩個金牌三寶飯。"],
        "variant": "白飯。",
        "mode": "可以外送嗎？", "time": "盡快。", "address": "",
        "expect": {"lines": {"玫瑰油雞飯（五穀飯）": 1, "金牌三寶飯（白飯）": 2}, "total": 380, "mode": "pickup"},
    },
}
CONTACT = "我叫王小明，電話零九一二三四五六七八。"


def reply_for(text: str, sc: dict, state: dict) -> str:
    t = text.lower()
    last = [x for x in re.split(r"[。！？!?]", t) if x.strip()]
    last = last[-1] if last else t
    if re.search(r"只提供自取|只能自取|不提供外送|沒有外送|不外送|無法外送", t):
        return "好，那我自取。"
    if re.search(r"白飯.{0,6}五穀飯|五穀飯.{0,6}白飯", last) and sc.get("variant"):
        return sc["variant"]
    if re.search(r"三百五|350|最低|門檻|不足|差", t) and sc.get("upsell") and not state.get("upsold"):
        state["upsold"] = True
        return sc["upsell"]
    if re.search(r"(對嗎|對不對|確認|沒問題嗎|可以嗎|正確嗎)\W*$", last.strip()) and not re.search(r"地址|電話|名字|姓名|自取|外送|幾點|時間", last):
        return "對，沒錯。"
    if re.search(r"地址", last):
        return sc["address"] or "我自取。"
    if re.search(r"電話|手機|名字|姓名|貴姓|稱呼", last):
        return CONTACT
    if re.search(r"自取|外送|外帶", last):
        return sc["mode"]
    if re.search(r"幾點|時間|什麼時候|何時", last):
        return sc["time"]
    if re.search(r"哪一|哪個|哪種|還是", last):
        return "第一個。"
    if re.search(r"還需要|還要|其他|別的|加點|什麼嗎", last):
        if state["queue"]:
            return state["queue"].pop(0)
        return "就這樣。"
    if state["queue"]:
        return state["queue"].pop(0)
    return "好，謝謝。"


async def run(name: str) -> dict:
    sc = SCENARIOS[name]
    ud = agent.Userdata(store=menu.load_store(sc["store"]), room=None)
    state = {"queue": list(sc["items"])}
    transcript = []
    async with agent.build_llm() as llm, AgentSession(
        llm=llm, userdata=ud, max_tool_steps=5, conn_options=agent.session_conn_options()
    ) as session:
        await session.start(agent.OrderTaker(ud.store))
        line = state["queue"].pop(0)
        for _ in range(20):
            transcript.append(f"CALLER: {line}")
            t0 = time.time()
            res = await asyncio.wait_for(session.run(user_input=line), timeout=180)
            reply = ""
            for ev in res.events:
                k = type(ev).__name__
                if k == "FunctionCallEvent":
                    transcript.append(f"   [tool] {ev.item.name}({ev.item.arguments})")
                elif k == "ChatMessageEvent" and ev.item.role == "assistant":
                    reply = ev.item.text_content or ""
                    transcript.append(f"AGENT ({time.time() - t0:.1f}s): {reply}")
            if ud.order.status != "open":
                break
            line = reply_for(reply, sc, state)
    o = ud.order
    got = {ln.label: ln.quantity for ln in o.lines}
    exp = sc["expect"]
    ok = o.status == "confirmed" and got == exp["lines"] and o.total == exp["total"] and o.mode == exp["mode"]
    return {"scenario": name, "ok": ok, "status": o.status, "lines": got, "total": o.total,
            "mode": o.mode, "order_no": o.order_no, "transcript": transcript}


async def main() -> None:
    names = sys.argv[1:] or list(SCENARIOS)
    from livekit.agents.utils import http_context
    http_context._new_session_ctx()  # a job context normally provides this
    results = [await run(n) for n in names]
    for r in results:
        print("\n".join(r["transcript"]))
        print(f"==> {r['scenario']}: {'PASS' if r['ok'] else 'FAIL'} status={r['status']} "
              f"lines={r['lines']} total={r['total']} mode={r['mode']} no={r['order_no']}\n")
    print("SUMMARY:", ", ".join(f"{r['scenario']}={'PASS' if r['ok'] else 'FAIL'}" for r in results))


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from benchmark import build_expected, diff_databases
from common import Userdata
from dotenv import load_dotenv
from fake_data.seed import build_seed_bytes
from hotel_db import (
    TODAY,
    HotelDB,
)
from instructions import build_instructions
from policies import build_lookup_policy_tool
from run_artifacts import dump_run_artifacts
from tools_restaurant import RestaurantToolsMixin
from tools_rooms import RoomToolsMixin
from tools_services import ServicesToolsMixin
from ui_view import UiView

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    SimulationContext,
    cli,
    inference,
)
from livekit.agents.evals import (
    JudgeGroup,
    accuracy_judge,
    coherence_judge,
    conciseness_judge,
    handoff_judge,
    relevancy_judge,
    safety_judge,
    task_completion_judge,
    tool_use_judge,
)

load_dotenv(".env.local")

logger = logging.getLogger("hotel-receptionist")


class HotelReceptionistAgent(RoomToolsMixin, RestaurantToolsMixin, ServicesToolsMixin, Agent):
    def __init__(self) -> None:
        super().__init__(instructions=build_instructions(), tools=[build_lookup_policy_tool()])

    async def on_enter(self) -> None:
        # The caller may have already said what they want before we speak -
        # pick up from there instead of re-asking "how can I help?".
        await self.session.generate_reply(
            instructions=(
                "Greet the caller in one short sentence. If they've already named a need "
                "(a room, a table, a cancellation...), move straight into helping; "
                "otherwise ask how you can help."
            )
        )


server = AgentServer()

_SEED_DB_BYTES = build_seed_bytes(TODAY)


async def on_simulation_end(ctx: SimulationContext) -> None:
    # Grade the run on final DB state: build the scenario's `expected_state` on a
    # fresh seed, then diff it against the agent's DB. The diff compares
    # agent-decided facts only (room type, dates, extras, status), so minted
    # codes / order / which-king don't matter and the agent need not reproduce the
    # statements — while collateral damage still surfaces.
    expected_state = ctx.userdata().get("expected_state") or []
    if not expected_state:
        return

    session = ctx.job_context.primary_session
    expected = await build_expected(_SEED_DB_BYTES, expected_state)
    try:
        diffs = diff_databases(expected.connection, session.userdata.db.connection)
    finally:
        await expected.aclose()

    # Veto the run if the final DB state diverged. The effective result is the AND of
    # this check and the simulator's conversation judgment, so a mismatch fails a run
    # the simulator passed; a match simply leaves the simulator's verdict to stand.
    if diffs:
        ctx.fail(reason="final DB diverges from expected: " + " | ".join(diffs[:8]))


async def on_session_end(ctx: JobContext) -> None:
    try:
        report = ctx.make_session_report()
    except RuntimeError:
        return

    chat = report.chat_history.copy(exclude_function_call=True, exclude_instructions=True)
    if len(chat.items) < 3:
        return

    judges = JudgeGroup(
        llm="openai/gpt-4.1-mini",
        judges=[
            task_completion_judge(),
            accuracy_judge(),
            tool_use_judge(),
            handoff_judge(),
            safety_judge(),
            relevancy_judge(),
            coherence_judge(),
            conciseness_judge(),
        ],
    )
    await judges.evaluate(report.chat_history)

    userdata = ctx.primary_session.userdata

    db_diffs: list[str] = []
    try:
        sim_ctx = ctx.simulation_context()
        if sim_ctx is None:
            logger.info(
                "local expected-state diff skipped: no simulation context "
                "(job/room metadata carried no SimulationDispatch)"
            )
        expected_state = (sim_ctx.userdata().get("expected_state") if sim_ctx else None) or []
        if sim_ctx is not None and not expected_state:
            logger.info("local expected-state diff skipped: scenario has no expected_state")
        if expected_state:
            logger.info("running local expected-state diff (%d statement(s))", len(expected_state))
            expected = await build_expected(_SEED_DB_BYTES, expected_state)
            try:
                db_diffs = diff_databases(expected.connection, userdata.db.connection)
            finally:
                await expected.aclose()
    except Exception:
        logger.exception("error running local expected-state diff")

    # "Did the call do real work?" is a DB question, not per-tool bookkeeping:
    # compare the final DB against the untouched seed. Any change in the
    # transactional tables (booking, cancellation, modification, dispute,
    # followup, late-arrival note...) counts.
    try:
        seed_db = HotelDB.from_bytes(_SEED_DB_BYTES)
        try:
            state_changes = diff_databases(seed_db.connection, userdata.db.connection)
        finally:
            await seed_db.aclose()
    except Exception:
        logger.exception("error diffing final DB against seed")
        state_changes = []

    # Read-only calls (policy questions, availability checks, booking lookups)
    # are real work too - a Q&A call that answered from a successful read tool
    # shouldn't be tagged as having accomplished nothing.
    read_tools = {
        "lookup_policy",
        "lookup_booking",
        "lookup_invoice",
        "lookup_restaurant_reservation",
        "check_room_availability",
        "check_restaurant_availability",
        "lookup_guest_history",
    }
    call_names = {
        item.call_id: item.name
        for item in report.chat_history.items
        if item.type == "function_call"
    }
    served_reads = any(
        item.type == "function_call_output"
        and not item.is_error
        and call_names.get(item.call_id) in read_tools
        for item in report.chat_history.items
    )

    if db_diffs:
        ctx.tagger.fail(reason="final DB diverges from expected: " + " | ".join(db_diffs[:8]))
    elif state_changes or served_reads:
        ctx.tagger.success()
    else:
        ctx.tagger.fail(
            reason="The call accomplished nothing: no state was changed (booking, "
            "cancellation, modification, dispute, followup, message, wake-up call...) "
            "and no information was looked up for the caller."
        )

    logger.info("session tags: %s", ctx.tagger.tags)

    dump_run_artifacts(ctx, report, userdata.db)

    try:
        await userdata.db.aclose()
    except Exception:
        logger.exception("error closing hotel DB")


def _build_llm():
    """Select the LLM backend.

    Default: LiveKit Cloud Inference (``google/gemma-4-31b-it``).
    Set ``LLM_BACKEND=local`` in ``.env.local`` to use a local OpenAI-compatible
    server such as ``mlx_lm.server`` on Apple Silicon (Phase 2 / MLX). Override the
    model/endpoint with ``LOCAL_LLM_MODEL`` / ``LOCAL_LLM_BASE_URL``.
    """
    if os.getenv("LLM_BACKEND", "cloud").lower() == "local":
        from livekit.plugins import openai

        model = os.getenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3-8B-4bit")
        extra_body = {}
        if "qwen3" in model.lower():
            # Qwen3 defaults to "thinking" mode (slow, rambly) — disable it for voice.
            extra_body = {"chat_template_kwargs": {"enable_thinking": False}}
        return openai.LLM(
            model=model,
            base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
            api_key="not-needed",
            extra_body=extra_body,
        )
    return inference.LLM("google/gemma-4-31b-it")


def _build_tts():
    """Select the TTS backend.

    Default: LiveKit Cloud Inference (``inworld/inworld-tts-2``).
    Set ``TTS_BACKEND=local`` in ``.env.local`` to use a local OpenAI-compatible
    speech server such as ``mlx-audio`` + Kokoro on Apple Silicon (Phase 2 / MLX).
    """
    if os.getenv("TTS_BACKEND", "cloud").lower() == "local":
        from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
        from livekit.plugins import openai
        from livekit.plugins.openai.tts import AudioChunkedStream

        class _LocalTTS(openai.TTS):
            # mlx-audio's /v1/audio/speech returns raw audio bytes, not OpenAI's SSE
            # event stream. The base class picks the SSE transport for any non-OpenAI
            # model id, so force the raw-bytes transport here. (Pinned to
            # livekit-plugins-openai 1.6.6; AudioChunkedStream is an internal name.)
            def synthesize(self, text, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
                return AudioChunkedStream(tts=self, input_text=text, conn_options=conn_options)

        return _LocalTTS(
            model=os.getenv("LOCAL_TTS_MODEL", "mlx-community/Kokoro-82M-bf16"),
            voice=os.getenv("LOCAL_TTS_VOICE", "af_heart"),
            base_url=os.getenv("LOCAL_TTS_BASE_URL", "http://127.0.0.1:8000/v1"),
            api_key="not-needed",
            response_format="wav",
        )
    return inference.TTS("inworld/inworld-tts-2")


def _build_stt():
    """Select the STT backend.

    Default: LiveKit Cloud Inference (``deepgram/nova-3``).
    Set ``STT_BACKEND=local`` in ``.env.local`` to use local mlx-audio Qwen3-ASR
    (Phase 2 / MLX). It's non-streaming, so AgentSession wraps it with the
    session VAD (StreamAdapter) — each end-of-speech utterance is transcribed once.
    """
    if os.getenv("STT_BACKEND", "cloud").lower() == "local":
        from local_stt import MLXQwen3STT

        return MLXQwen3STT(
            model=os.getenv("LOCAL_STT_MODEL", "mlx-community/Qwen3-ASR-1.7B-8bit"),
            language=os.getenv("LOCAL_STT_LANGUAGE", "en"),
        )
    return inference.STT("deepgram/nova-3")


@server.rtc_session(on_session_end=on_session_end, on_simulation_end=on_simulation_end)
async def hotel_receptionist_agent(ctx: JobContext) -> None:
    await ctx.connect()

    db = HotelDB.from_bytes(_SEED_DB_BYTES)

    ui = UiView(ctx.room, db.connection)
    db.on_change = ui.on_change
    await ui.start()

    userdata = Userdata(db=db)
    session = AgentSession[Userdata](
        userdata=userdata,
        # An explicit VAD is required (not the bundled default): without it the
        # speaking anchor falls back to the STT stream clock, which drifts into the
        # future across a long call / nested-task switch and makes the turn-commit
        # logic sleep for that offset (~the elapsed call time) before replying.
        vad=inference.VAD(model="silero"),
        stt=_build_stt(),
        llm=_build_llm(),
        tts=_build_tts(),
        max_tool_steps=5,
    )

    await session.start(agent=HotelReceptionistAgent(), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)

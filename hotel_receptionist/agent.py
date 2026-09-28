from __future__ import annotations

import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# Load before the local imports: persona.py reads AGENT_LANGUAGE at import time.
load_dotenv(".env.local")

from benchmark import build_expected, diff_databases
from common import Userdata
from fake_data.seed import build_seed_bytes
from hotel_db import (
    TODAY,
    HotelDB,
)
from instructions import build_instructions
from languages import current_language
from policies import build_lookup_policy_tool
from run_artifacts import dump_run_artifacts
from tools_restaurant import RestaurantToolsMixin
from tools_rooms import RoomToolsMixin
from tools_services import ServicesToolsMixin
from ui_view import UiView

from livekit.agents import (
    Agent,
    APIConnectOptions,
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
from livekit.agents.voice.agent_session import SessionConnectOptions

logger = logging.getLogger("hotel-receptionist")

if "local" in (os.getenv("LLM_BACKEND", "").lower(), os.getenv("TTS_BACKEND", "").lower()):
    # LiveKit plugins must register on the main thread, and `console` runs the job
    # on a worker thread - so import here, not lazily inside _build_llm/_build_tts.
    # (livekit-plugins-openai is only in requirements-local.txt, hence the guard.)
    from livekit.plugins import openai as _openai_plugin  # noqa: F401


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
    server such as ``mlx_lm.server`` on Apple Silicon (Phase 2 / MLX); default model
    Qwen3-8B - the only small local model that drove the tool-based booking flow
    (survey: GitHub issue #8). Override the
    model/endpoint with ``LOCAL_LLM_MODEL`` / ``LOCAL_LLM_BASE_URL``.
    """
    if os.getenv("LLM_BACKEND", "cloud").lower() == "local":
        from livekit.plugins import openai

        model = os.getenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3-8B-4bit")
        base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080/v1")
        client = None
        if "qwen3.5" in model.lower():
            client = _single_system_client(base_url)
        return openai.LLM(
            model=model,
            base_url=base_url,
            client=client,
            api_key="not-needed",
            # Qwen3 (and Gemma 4) "think" by default under mlx_lm.server (slow,
            # rambly, and the reply lands in a separate reasoning field) - disable it
            # for voice. Templates without the flag just ignore it.
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    return inference.LLM(current_language().cloud_llm_model or "google/gemma-4-31b-it")


def _single_system_client(base_url: str):
    """OpenAI client whose requests keep only the leading system message.

    Qwen3.5's chat template raises "System message must be at the beginning", but
    LiveKit inserts system messages mid-conversation (AgentTask handoffs,
    generate_reply(instructions=...)). Rewrite each later one in place as a labeled
    user note; merging it into the first system message would change the ~16.5k-token
    prompt prefix and defeat mlx_lm.server's prompt cache.
    """
    import json

    import httpx
    import openai as openai_sdk

    class _Rewrite(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self._inner = httpx.AsyncHTTPTransport()

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/chat/completions"):
                body = json.loads(await request.aread())
                for i, m in enumerate(body.get("messages", [])):
                    if i and m.get("role") == "system":
                        m["role"] = "user"
                        m["content"] = f"[Instruction from the system, not the caller] {m['content']}"
                headers = {k: v for k, v in request.headers.items() if k != "content-length"}
                request = httpx.Request(request.method, request.url, headers=headers, json=body)
            return await self._inner.handle_async_request(request)

        async def aclose(self) -> None:
            await self._inner.aclose()

    return openai_sdk.AsyncClient(
        api_key="not-needed",
        base_url=base_url,
        http_client=httpx.AsyncClient(transport=_Rewrite(), timeout=httpx.Timeout(600, connect=10)),
    )


def _build_tts():
    """Select the TTS backend.

    Default: LiveKit Cloud Inference (``inworld/inworld-tts-2``).
    Set ``TTS_BACKEND=local`` in ``.env.local`` to use a local OpenAI-compatible
    speech server such as ``mlx-audio`` + Kokoro on Apple Silicon (Phase 2 / MLX).
    """
    if os.getenv("TTS_BACKEND", "cloud").lower() == "local":
        import json

        import httpx
        import openai as openai_sdk

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

        class _AddLangCode(httpx.AsyncBaseTransport):
            # mlx-audio defaults Kokoro to lang_code "a" (American English G2P), and
            # openai.TTS can't send extra body fields - so add it on the wire.
            def __init__(self, lang_code: str) -> None:
                self._lang_code = lang_code
                self._inner = httpx.AsyncHTTPTransport()

            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                if request.url.path.endswith("/audio/speech"):
                    body = json.loads(await request.aread())
                    body["lang_code"] = self._lang_code
                    headers = {k: v for k, v in request.headers.items() if k != "content-length"}
                    request = httpx.Request(request.method, request.url, headers=headers, json=body)
                return await self._inner.handle_async_request(request)

            async def aclose(self) -> None:
                await self._inner.aclose()

        lang = current_language()
        model = os.getenv("LOCAL_TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
        voice = os.getenv("LOCAL_TTS_VOICE") or lang.kokoro_voice
        base_url = os.getenv("LOCAL_TTS_BASE_URL", "http://127.0.0.1:8000/v1")
        client = None
        if "kokoro" in model.lower():
            # Kokoro voice ids start with their G2P language code (af_heart -> "a").
            if voice[0] not in lang.kokoro_lang_codes:
                logger.warning(
                    "LOCAL_TTS_VOICE=%s doesn't match AGENT_LANGUAGE=%s (try %s)",
                    voice, lang.code, lang.kokoro_voice,
                )
            client = openai_sdk.AsyncClient(
                api_key="not-needed",
                base_url=base_url,
                http_client=httpx.AsyncClient(transport=_AddLangCode(voice[0])),
            )

        return _LocalTTS(
            model=model,
            voice=voice,
            base_url=base_url,
            api_key="not-needed",
            response_format="wav",
            client=client,
        )
    lang = current_language()
    kwargs = {}
    if lang.cloud_tts_voice:
        kwargs["voice"] = lang.cloud_tts_voice
    if lang.cloud_tts_language:
        kwargs["language"] = lang.cloud_tts_language
    return inference.TTS(lang.cloud_tts_model or "inworld/inworld-tts-2", **kwargs)


def _build_stt(vad):
    """Select the STT backend.

    Default: LiveKit Cloud Inference (``deepgram/nova-3``).
    Set ``STT_BACKEND=local`` in ``.env.local`` for local mlx-audio STT (Phase 2 /
    MLX). The model defaults from ``AGENT_LANGUAGE`` (override: ``LOCAL_STT_MODEL``):
    a Nemotron streaming model gets the streaming plugin (interim transcripts, final
    right after end-of-speech; segmented by its own stream of ``vad``); anything
    else is batch Qwen3-ASR, which AgentSession wraps with the session VAD
    (StreamAdapter) - each end-of-speech utterance is transcribed once.
    """
    if os.getenv("STT_BACKEND", "cloud").lower() == "local":
        from local_stt import MLXNemotronStreamingSTT, MLXQwen3STT

        lang = current_language()
        model = os.getenv("LOCAL_STT_MODEL") or lang.stt_model
        language = os.getenv("LOCAL_STT_LANGUAGE") or lang.stt_language
        if "nemotron" in model.lower():
            return MLXNemotronStreamingSTT(vad=vad, model=model, language=language)
        return MLXQwen3STT(model=model, language=language)
    lang = current_language()
    kwargs = {}
    if lang.cloud_stt_language:
        kwargs["language"] = lang.cloud_stt_language
    return inference.STT(lang.cloud_stt_model or "deepgram/nova-3", **kwargs)


def _session_conn_options() -> SessionConnectOptions:
    # A local LLM prefills the ~16.5k-token prompt cold on the first turn (and on
    # each AgentTask's first turn): ~1 min on an M1 Max, far past the default 10 s
    # timeout. Retrying doesn't help - the abandoned request keeps the server busy.
    if os.getenv("LLM_BACKEND", "cloud").lower() != "local":
        return SessionConnectOptions()
    timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "180"))
    return SessionConnectOptions(llm_conn_options=APIConnectOptions(timeout=timeout, max_retry=1))


@server.rtc_session(on_session_end=on_session_end, on_simulation_end=on_simulation_end)
async def hotel_receptionist_agent(ctx: JobContext) -> None:
    await ctx.connect()

    db = HotelDB.from_bytes(_SEED_DB_BYTES)

    ui = UiView(ctx.room, db.connection)
    db.on_change = ui.on_change
    await ui.start()

    userdata = Userdata(db=db)
    # An explicit VAD is required (not the bundled default): without it the
    # speaking anchor falls back to the STT stream clock, which drifts into the
    # future across a long call / nested-task switch and makes the turn-commit
    # logic sleep for that offset (~the elapsed call time) before replying.
    vad = inference.VAD(model="silero")
    session = AgentSession[Userdata](
        userdata=userdata,
        vad=vad,
        stt=_build_stt(vad),
        llm=_build_llm(),
        tts=_build_tts(),
        max_tool_steps=5,
        conn_options=_session_conn_options(),
    )

    await session.start(agent=HotelReceptionistAgent(), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)

"""STT / LLM / TTS builders shared by the voice-agent apps.

Each slot is chosen by an env var (default ``cloud``): ``LLM_BACKEND`` / ``TTS_BACKEND`` /
``STT_BACKEND`` = ``cloud`` (LiveKit Inference) | ``local`` (MLX on Apple Silicon). Language
defaults come from ``voiceshared.profiles`` (``AGENT_LANGUAGE``). Moved verbatim from
hotel_receptionist/agent.py; see the repo CLAUDE.md for the local-model gotchas.
"""

from __future__ import annotations

import logging
import os

from livekit.agents import APIConnectOptions, AgentServer, inference
from livekit.agents.voice.agent_session import SessionConnectOptions

from voiceshared.profiles import current_profile

logger = logging.getLogger("voiceshared.backends")

if "local" in (os.getenv("LLM_BACKEND", "").lower(), os.getenv("TTS_BACKEND", "").lower()):
    # LiveKit plugins must register on the main thread, and `console` runs the job
    # on a worker thread - so import here (apps import this module at load time), not
    # lazily inside build_llm/build_tts. (livekit-plugins-openai is only in
    # requirements-local.txt, hence the guard.)
    from livekit.plugins import openai as _openai_plugin  # noqa: F401


def agent_server() -> AgentServer:
    """AgentServer with optional overrides for several workers on one machine:
    AGENT_HTTP_PORT avoids the 8081 health-port clash, and AGENT_IDLE_PROCESSES caps
    pre-warmed job processes (production default = one per CPU core, each loading the
    whole agent). Unset = upstream defaults."""
    opts: dict = {}
    if os.getenv("AGENT_HTTP_PORT"):
        opts["port"] = int(os.environ["AGENT_HTTP_PORT"])
    if os.getenv("AGENT_IDLE_PROCESSES"):
        opts["num_idle_processes"] = int(os.environ["AGENT_IDLE_PROCESSES"])
    return AgentServer(**opts)


def agent_name() -> str:
    """AGENT_NAME empty = automatic dispatch (joins every new room). Set it when several
    workers share one LiveKit project, so each web front-end dispatches its own agent."""
    return os.getenv("AGENT_NAME", "")


def build_llm():
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
            client = single_system_client(base_url)
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
    return inference.LLM(current_profile().cloud_llm_model or "google/gemma-4-31b-it")


def single_system_client(base_url: str):
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


def build_tts():
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

        lang = current_profile()
        model = os.getenv("LOCAL_TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
        voice = os.getenv("LOCAL_TTS_VOICE") or lang.kokoro_voice
        base_url = os.getenv("LOCAL_TTS_BASE_URL", "http://127.0.0.1:8000/v1")
        client = None
        if "kokoro" in model.lower():
            # Kokoro voice ids start with their G2P language code (af_heart -> "a").
            if voice[0] not in lang.kokoro_lang_codes:
                logger.warning(
                    "LOCAL_TTS_VOICE=%s doesn't match AGENT_LANGUAGE=%s (try %s)",
                    voice, lang.key, lang.kokoro_voice,
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
    lang = current_profile()
    kwargs = {}
    if lang.cloud_tts_voice:
        kwargs["voice"] = lang.cloud_tts_voice
    if lang.cloud_tts_language:
        kwargs["language"] = lang.cloud_tts_language
    return inference.TTS(lang.cloud_tts_model or "inworld/inworld-tts-2", **kwargs)


def build_stt(vad):
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
        from voiceshared.local_stt import MLXNemotronStreamingSTT, MLXQwen3STT

        lang = current_profile()
        model = os.getenv("LOCAL_STT_MODEL") or lang.stt_model
        language = os.getenv("LOCAL_STT_LANGUAGE") or lang.stt_language
        if "nemotron" in model.lower():
            return MLXNemotronStreamingSTT(vad=vad, model=model, language=language)
        return MLXQwen3STT(model=model, language=language)
    lang = current_profile()
    kwargs = {}
    if lang.cloud_stt_language:
        kwargs["language"] = lang.cloud_stt_language
    return inference.STT(lang.cloud_stt_model or "deepgram/nova-3", **kwargs)


def session_conn_options() -> SessionConnectOptions:
    # A local LLM prefills the ~16.5k-token prompt cold on the first turn (and on
    # each AgentTask's first turn): ~1 min on an M1 Max, far past the default 10 s
    # timeout. Retrying doesn't help - the abandoned request keeps the server busy.
    if os.getenv("LLM_BACKEND", "cloud").lower() != "local":
        return SessionConnectOptions()
    timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "180"))
    return SessionConnectOptions(llm_conn_options=APIConnectOptions(timeout=timeout, max_retry=1))

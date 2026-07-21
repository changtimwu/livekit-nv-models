"""Local speech-to-text for the hotel receptionist, using mlx-audio's Qwen3-ASR
on Apple Silicon (Phase 2 / MLX).

Why a custom plugin instead of mlx-audio's HTTP server: MLX's GPU stream is
thread-local. mlx-audio's `mlx_audio.server` loads the model on one thread and
runs generation on a worker thread, which crashes with
`RuntimeError: There is no Stream(gpu, 0) in current thread`. Here we load AND
run the model on a single dedicated worker thread, so every MLX op shares one
stream — the same code path that works standalone.

The model is non-streaming (batch). We report `streaming=False`, so AgentSession
wraps this with `StreamAdapter` driven by the session VAD: each end-of-speech
utterance is transcribed in one call.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import tempfile

from livekit import rtc
from livekit.agents import stt
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer


class MLXQwen3STT(stt.STT):
    def __init__(
        self,
        *,
        model: str = "mlx-community/Qwen3-ASR-1.7B-8bit",
        language: str = "en",
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        self._model_repo = model
        self._language = language
        self._model = None
        # One dedicated thread for both load and generate (see module docstring).
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mlx-qwen3-asr"
        )

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        if self._model is None:
            from mlx_audio.stt.utils import load_model

            self._model = load_model(self._model_repo)

        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav_bytes)
            out = self._model.generate(path)  # returns STTOutput
            return (getattr(out, "text", "") or "").strip()
        finally:
            os.unlink(path)

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        wav_bytes = rtc.combine_audio_frames(buffer).to_wav_bytes()
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(self._executor, self._transcribe_sync, wav_bytes)
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(text=text, language=self._language)],
        )

    async def aclose(self) -> None:
        self._executor.shutdown(wait=False)

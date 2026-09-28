"""Local speech-to-text for the hotel receptionist, using mlx-audio's Qwen3-ASR
on Apple Silicon (Phase 2 / MLX).

Why a custom plugin instead of mlx-audio's HTTP server: MLX's GPU stream is
thread-local. mlx-audio's `mlx_audio.server` loads the model on one thread and
runs generation on a worker thread, which crashes with
`RuntimeError: There is no Stream(gpu, 0) in current thread`. Here we load AND
run the model on a single dedicated worker thread, so every MLX op shares one
stream — the same code path that works standalone.

Two plugins:

- `MLXQwen3STT` - Qwen3-ASR, batch. We report `streaming=False`, so AgentSession
  wraps it with `StreamAdapter` driven by the session VAD: each end-of-speech
  utterance is transcribed in one call. Best Mandarin accuracy.
- `MLXNemotronStreamingSTT` - NVIDIA Nemotron 3.5 ASR Streaming (cache-aware
  FastConformer-RNNT). Audio is transcribed while the caller speaks (interim
  transcripts); at VAD end-of-speech the stream is flushed, so the final
  transcript lands ~50-130 ms later instead of after a full batch pass. English
  only in practice (its Mandarin is unusable). See GitHub issue #6.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import tempfile

import numpy as np

from livekit import rtc
from livekit.agents import stt, utils, vad
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


# Nemotron language prompts are locales; accept the short codes used elsewhere.
_NEMOTRON_LOCALES = {"en": "en-US", "zh": "zh-CN"}


class MLXNemotronStreamingSTT(stt.STT):
    """Streaming local STT. Utterances are segmented by our own VAD stream (like
    livekit's StreamAdapter): audio is fed continuously, and each VAD
    end-of-speech closes the Nemotron session, emits FINAL, and resets it.
    """

    def __init__(
        self,
        *,
        vad: vad.VAD,
        model: str = "mlx-community/nemotron-3.5-asr-streaming-0.6b",
        language: str = "en",
        att_context_size: tuple[int, int] = (56, 3),  # 320 ms chunks (issue #6)
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self._vad = vad
        self._model_repo = model
        self._language = language
        self._locale = _NEMOTRON_LOCALES.get(language, language)
        self._att_context_size = list(att_context_size)
        self._model = None
        # One dedicated thread for load + every session op (see module docstring).
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mlx-nemotron-asr"
        )

    @property
    def model(self) -> str:
        return self._model_repo

    @property
    def provider(self) -> str:
        return "mlx-audio"

    def _load_sync(self):
        if self._model is None:
            from mlx_audio.stt.utils import load_model

            self._model = load_model(self._model_repo)
            self._model.default_att_context_size = self._att_context_size
        return self._model

    def _new_session_sync(self):
        return self._load_sync().create_streaming_session(language=self._locale)

    def _transcribe_sync(self, samples: np.ndarray) -> str:
        sess = self._new_session_sync()
        sess.feed(samples)
        sess.close()
        return _drain(sess, until_done=True).strip()

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        frame = rtc.combine_audio_frames(buffer)
        if frame.sample_rate != 16000:
            frame = _resample(frame, 16000)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(self._executor, self._transcribe_sync, _to_float(frame))
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(text=text, language=self._language)],
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        return _NemotronStream(stt=self, conn_options=conn_options)

    async def aclose(self) -> None:
        self._executor.shutdown(wait=False)


class _NemotronStream(stt.RecognizeStream):
    def __init__(self, *, stt: MLXNemotronStreamingSTT, conn_options) -> None:
        # sample_rate=16000 makes the base class resample incoming frames.
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=16000)
        self._owner = stt

    async def _run(self) -> None:
        owner = self._owner
        loop = asyncio.get_running_loop()
        vad_stream = owner._vad.stream()
        pending: list[np.ndarray] = []
        wake = asyncio.Event()
        finalize = False
        sess = await loop.run_in_executor(owner._executor, owner._new_session_sync)
        text = ""

        def emit(kind: stt.SpeechEventType, t: str) -> None:
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=kind,
                    alternatives=[stt.SpeechData(text=t, language=owner._language)],
                )
            )

        def work(audio: np.ndarray | None, flush: bool) -> tuple[str, str | None]:
            # Runs on the MLX thread; the session is only ever touched here.
            nonlocal sess
            if audio is not None and audio.size:
                sess.feed(audio)
            if not flush:
                return _drain(sess), None
            sess.close()
            tail = _drain(sess, until_done=True)
            sess = owner._new_session_sync()
            return tail, "flushed"

        async def decode_loop() -> None:
            nonlocal finalize, text
            while True:
                await wake.wait()
                wake.clear()
                audio = np.concatenate(pending) if pending else None
                pending.clear()
                flush, finalize = finalize, False
                delta, flushed = await loop.run_in_executor(owner._executor, work, audio, flush)
                if delta:
                    text += delta
                    if not flushed:
                        emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, text.strip())
                if flushed:
                    if text.strip():
                        emit(stt.SpeechEventType.FINAL_TRANSCRIPT, text.strip())
                    text = ""
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                    )

        async def vad_loop() -> None:
            nonlocal finalize
            async for ev in vad_stream:
                if ev.type == vad.VADEventType.START_OF_SPEECH:
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                elif ev.type == vad.VADEventType.END_OF_SPEECH:
                    finalize = True
                    wake.set()

        async def input_loop() -> None:
            async for data in self._input_ch:
                if isinstance(data, self._FlushSentinel):
                    vad_stream.flush()
                    continue
                vad_stream.push_frame(data)
                pending.append(_to_float(data))
                wake.set()
            vad_stream.end_input()

        tasks = [
            asyncio.create_task(input_loop()),
            asyncio.create_task(vad_loop()),
            asyncio.create_task(decode_loop()),
        ]
        try:
            await asyncio.gather(*tasks[:2])
        finally:
            await utils.aio.cancel_and_wait(*tasks)
            await vad_stream.aclose()


def _drain(sess, *, until_done: bool = False) -> str:
    """Step the session until the audio fed so far is consumed (or, after close(),
    until it is done). step() only ingests a new encoder chunk once the encoded
    frames are used up, so one call isn't enough. Reads NemotronStreamingSession
    internals (_encoded/_queued/chunk size) - pinned to mlx-audio 0.5.x."""
    chunk = sess._encoder.chunk_mel * sess.model.preprocessor_config.hop_length
    out = []
    while not sess.done:
        out.extend(sess.step(max_decode_tokens=64))
        if not until_done and not sess._encoded and sess._queued < chunk:
            break
    return "".join(out)


def _to_float(frame: rtc.AudioFrame) -> np.ndarray:
    x = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
    if frame.num_channels > 1:
        x = x.reshape(-1, frame.num_channels).mean(axis=1)
    return x


def _resample(frame: rtc.AudioFrame, rate: int) -> rtc.AudioFrame:
    rs = rtc.AudioResampler(frame.sample_rate, rate, num_channels=frame.num_channels)
    return rtc.combine_audio_frames(rs.push(frame) + rs.flush())

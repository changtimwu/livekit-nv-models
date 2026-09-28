"""Per-language speech and model defaults, selected with ``AGENT_LANGUAGE`` (default ``en``).

A profile carries the local (Phase 2 / MLX) voice slots and the cloud (LiveKit Inference)
STT / TTS / LLM picks for that language. Explicit ``LOCAL_TTS_VOICE`` / ``LOCAL_STT_MODEL`` /
``LOCAL_STT_LANGUAGE`` env vars still win. ``cloud_*`` = ``None`` means leave the upstream
default untouched, as ``en`` does.

Profiles: ``en``, ``zh`` (mainland Mandarin, Simplified) and ``zh-tw`` (Taiwan Mandarin,
Traditional; ``zh_tw`` also accepted). Evaluation: GitHub issue #1. Each app adds its own
prompt directive per language (e.g. hotel_receptionist/languages.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechProfile:
    key: str  # AGENT_LANGUAGE value (en / zh / zh-tw)
    code: str
    stt_language: str  # label reported by the local STT (Qwen3-ASR auto-detects)
    stt_model: str  # default local STT; nemotron = streaming, else batch Qwen3-ASR
    kokoro_voice: str  # Kokoro voice ids are prefixed with their G2P lang code
    kokoro_lang_codes: str  # voice prefixes that fit this language
    # LiveKit Inference (cloud) settings; None = don't pass (upstream default)
    cloud_llm_model: str | None = None
    cloud_stt_model: str | None = None
    cloud_stt_language: str | None = None
    cloud_tts_model: str | None = None
    cloud_tts_voice: str | None = None
    cloud_tts_language: str | None = None


PROFILES: dict[str, SpeechProfile] = {
    "en": SpeechProfile(
        key="en",
        code="en",
        stt_language="en",
        # Streaming: final transcript ~0.1 s after end-of-speech (issue #6).
        stt_model="mlx-community/nemotron-3.5-asr-streaming-0.6b",
        kokoro_voice="af_heart",
        kokoro_lang_codes="ab",
    ),
    "zh": SpeechProfile(
        key="zh",
        code="zh",
        stt_language="zh",
        # Batch: Nemotron's Mandarin is unusable; Qwen3-ASR is the most accurate.
        stt_model="mlx-community/Qwen3-ASR-1.7B-8bit",
        kokoro_voice="zf_xiaobei",
        kokoro_lang_codes="z",
        # Cloud picks from the #1 evaluation (LiveKit Inference only).
        cloud_stt_model="assemblyai/u3-rt-pro",  # best mainland CER; Simplified output
        cloud_stt_language="zh",
        cloud_tts_model="inworld/inworld-tts-2",
        cloud_tts_voice="Yichen",  # Inworld zh voices: Yichen / Xiaoyin / Xinyi / Jing
        cloud_tts_language="zh",
    ),
    "zh-tw": SpeechProfile(
        key="zh-tw",
        code="zh-TW",
        stt_language="zh-TW",
        stt_model="mlx-community/Qwen3-ASR-1.7B-8bit",
        # Kokoro has no Taiwan-accent voice; the mainland voice is the closest local option.
        kokoro_voice="zf_xiaobei",
        kokoro_lang_codes="z",
        # Cloud picks from the #1 evaluation (LiveKit Inference only).
        cloud_stt_model="deepgram/nova-3",  # the only hosted STT that outputs Traditional
        cloud_stt_language="zh-TW",
        # Cartesia's default voice was judged the most Taiwanese-sounding by ear. The
        # default is chosen server-side, so it can change without a code change.
        cloud_tts_model="cartesia/sonic-3.6",
        cloud_tts_language="zh",
    ),
}


def current_profile() -> SpeechProfile:
    key = os.getenv("AGENT_LANGUAGE", "en").strip().lower().replace("_", "-")
    if key not in PROFILES:
        raise ValueError(f"AGENT_LANGUAGE={key!r} is not one of {sorted(PROFILES)}")
    return PROFILES[key]


# Taiwan-Mandarin speaking rules that work around the current cloud TTS
# (cartesia/sonic-3.6; issue #18): it reads Arabic 2 as 兩 and 菸 as 八. Apps with a
# Chinese-first prompt can include this verbatim.
ZH_TW_SPEECH_RULES = """\
- Numbers: in the spoken reply, write every number in Chinese characters - never Arabic digits - because the TTS reads the digit 2 as "兩". Use 二 for the number two everywhere (dates "十月二日，星期五", money "二百四十元", times "晚上七點半"); keep 兩 only as a count before a measure word (兩個、兩份、兩位), which is how people in Taiwan say it.
- Whenever you say or repeat back a phone number, email address, order number or code, spell it one symbol at a time separated by "、" - never as a word or a whole number. Digits are single Chinese characters (零、一、二、三、四、五、六、七、八、九; 二, never 兩), letters stay English letters, "-" is "槓", and in an email "@" is "小老鼠" and "." is "點". Example: 0912-345-678 -> "零、九、一、二、三、四、五、六、七、八".
- Smoking: always write 煙, never 菸 (抽煙、吸煙) - the TTS misreads 菸 as "八"."""

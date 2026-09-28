"""Caller-facing language profiles, selected with ``AGENT_LANGUAGE`` (default ``en``).

The prompts stay in English for every language (they are shared with upstream and
the model follows them fine); a non-English profile appends a directive telling the
agent to speak that language and how to adapt the English-specific speaking rules.
Each profile also carries defaults for the local (Phase 2 / MLX) voice slots;
explicit ``LOCAL_TTS_VOICE`` / ``LOCAL_STT_MODEL`` / ``LOCAL_STT_LANGUAGE`` env vars
still win. The ``cloud_*`` fields configure LiveKit Inference STT / TTS for that
language (``None`` = leave the upstream default untouched, as ``en`` does).

Profiles: ``en``, ``zh`` (mainland Mandarin, Simplified) and ``zh-tw`` (Taiwan Mandarin,
Traditional; ``zh_tw`` also accepted). Evaluation: GitHub issue #1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    stt_language: str  # label reported by the local STT (Qwen3-ASR auto-detects)
    stt_model: str  # default local STT; nemotron = streaming, else batch Qwen3-ASR
    kokoro_voice: str  # Kokoro voice ids are prefixed with their G2P lang code
    kokoro_lang_codes: str  # voice prefixes that fit this language
    instructions: str  # appended to COMMON_INSTRUCTIONS ("" = none)
    # LiveKit Inference (cloud) settings; None = don't pass (upstream default)
    cloud_llm_model: str | None = None
    cloud_stt_model: str | None = None
    cloud_stt_language: str | None = None
    cloud_tts_model: str | None = None
    cloud_tts_voice: str | None = None
    cloud_tts_language: str | None = None


_ZH_INSTRUCTIONS = """

# Language
Everything the caller hears must be in Mandarin Chinese (Simplified Chinese, mainland usage), even though these instructions are written in English. If the caller clearly switches to English, follow them into English. Tool results come back in English - they are reference material; say what matters in Chinese, never read English tool text aloud.

The speaking rules above were written for English; apply them in Chinese like this:
- One short sentence per reply still holds - roughly fifteen to thirty characters.
- Numbers: digits are fine (the Chinese TTS reads "240美元" and "9月30日" correctly), but write money as "240美元", never with a "$" sign, and say dates the Chinese way ("9月30日，星期三").
- Never leave English words in a Chinese reply. Say room types in Chinese: king = 大床房, queen_2beds = 双床房, double_queen = 双大床房, suite = 套房, penthouse = 顶层套房; ocean view = 海景, city view = 城景, garden view = 花园景.
- Progressive release still applies: when a tool lists several options, first name only the kinds (e.g. "大床房、双床房、双大床房，还是套房？"), and give prices and views only after the caller picks.
- Codes (confirmation codes, card last four): read them one symbol at a time, keeping letters as English letters and digits as Chinese words, e.g. "H、T、L、杠、X、Q、七、Z".
- The English acknowledgments above ("Sure", "Mhm", "One sec", "Of course") are style examples; use natural Chinese ones such as "好的", "嗯", "稍等", "没问题", "当然", rotated the same way.
- Say the hotel's name as "LiveKit 酒店".
- Chinese names: when a character is ambiguous, ask how it's written (e.g. "弓长张还是立早章？") and record the name in Chinese characters exactly as confirmed. Email addresses are always Latin letters, spelled out letter by letter.
- The phone tool only accepts international format: pass mainland numbers as +86 followed by the number without a leading 0 (13812345678 -> "+8613812345678"; 010-1234-5678 -> "+861012345678"), but read it back the way the caller said it.
- Tool arguments keep the formats the tools expect (ISO dates, Latin-letter emails, numbers as digits) - only the spoken reply is Chinese."""


_ZH_TW_INSTRUCTIONS = """

# Language
Everything the caller hears must be in Taiwan Mandarin: Traditional Chinese characters (繁體中文) and the vocabulary and phrasing people in Taiwan actually use, even though these instructions are written in English. Never use Simplified characters or mainland-only terms. If the caller clearly switches to English, follow them into English; if they mix in Taiwanese Hokkien or English words, keep answering in Taiwan Mandarin. Tool results come back in English - they are reference material; say what matters in Chinese, never read English tool text aloud.

The speaking rules above were written for English; apply them in Taiwan Mandarin like this:
- One short sentence per reply still holds - roughly fifteen to thirty characters. Address the caller as "您".
- Say the hotel's name as "LiveKit 飯店" - never "酒店", which in Taiwan suggests a hostess club.
- Numbers: digits are fine, but write money as "240美元" (never with a "$" sign) and dates the Taiwan way ("10月2日，星期五").
- Never leave English words in a Chinese reply. Room types, Taiwan wording: king = 雙人房（一大床）, queen_2beds = 雙床房, double_queen = 兩大床房, suite = 套房, penthouse = 頂樓套房; ocean view = 海景, city view = 市景, garden view = 花園景.
- Progressive release still applies: when a tool lists several options, first name only the kinds (e.g. "雙人房、雙床房、兩大床房，還是套房？"), and give prices and views only after the caller picks.
- Codes (confirmation codes, card last four): read them one symbol at a time, keeping letters as English letters and digits as Chinese words, e.g. "H、T、L、槓、X、Q、七、Z".
- The English acknowledgments above ("Sure", "Mhm", "One sec", "Of course") are style examples; use natural Taiwan ones such as "好的", "了解", "沒問題", "稍等一下喔", "當然", rotated the same way.
- Chinese names: when a character is ambiguous, ask which character (e.g. "請問是弓長張還是立早章？", "耳東陳"), and record the name in Traditional characters exactly as confirmed. Email addresses are always Latin letters, spelled out letter by letter. Taiwan mobile numbers look like 0912-345-678. The phone tool only accepts international format, so pass +886 followed by the number without its leading 0 (0912-345-678 -> "+886912345678"; landline 02-2345-6789 -> "+886223456789"), but read it back to the caller the way they said it.
- Use Taiwan terms for common things: 信用卡, 手機 or 電話, 電子郵件 (or Email), 早餐, 停車位, 訂房, 確認碼.
- Tool arguments keep the formats the tools expect (ISO dates, Latin-letter emails, numbers as digits) - only the spoken reply is Chinese."""


PROFILES: dict[str, LanguageProfile] = {
    "en": LanguageProfile(
        code="en",
        stt_language="en",
        # Streaming: final transcript ~0.1 s after end-of-speech (issue #6).
        stt_model="mlx-community/nemotron-3.5-asr-streaming-0.6b",
        kokoro_voice="af_heart",
        kokoro_lang_codes="ab",
        instructions="",
    ),
    "zh": LanguageProfile(
        code="zh",
        stt_language="zh",
        # Batch: Nemotron's Mandarin is unusable; Qwen3-ASR is the most accurate.
        stt_model="mlx-community/Qwen3-ASR-1.7B-8bit",
        kokoro_voice="zf_xiaobei",
        kokoro_lang_codes="z",
        instructions=_ZH_INSTRUCTIONS,
        # Cloud picks from the #1 evaluation (LiveKit Inference only).
        cloud_stt_model="assemblyai/u3-rt-pro",  # best mainland CER; Simplified output
        cloud_stt_language="zh",
        cloud_tts_model="inworld/inworld-tts-2",
        cloud_tts_voice="Yichen",  # Inworld zh voices: Yichen / Xiaoyin / Xinyi / Jing
        cloud_tts_language="zh",
    ),
    "zh-tw": LanguageProfile(
        code="zh-TW",
        stt_language="zh-TW",
        stt_model="mlx-community/Qwen3-ASR-1.7B-8bit",
        # Kokoro has no Taiwan-accent voice; the mainland voice is the closest local option.
        kokoro_voice="zf_xiaobei",
        kokoro_lang_codes="z",
        instructions=_ZH_TW_INSTRUCTIONS,
        # Cloud picks from the #1 evaluation (LiveKit Inference only).
        cloud_stt_model="deepgram/nova-3",  # the only hosted STT that outputs Traditional
        cloud_stt_language="zh-TW",
        # Cartesia's default voice was judged the most Taiwanese-sounding by ear. The
        # default is chosen server-side, so it can change without a code change.
        cloud_tts_model="cartesia/sonic-3.6",
        cloud_tts_language="zh",
    ),
}


def current_language() -> LanguageProfile:
    code = os.getenv("AGENT_LANGUAGE", "en").strip().lower().replace("_", "-")
    if code not in PROFILES:
        raise ValueError(f"AGENT_LANGUAGE={code!r} is not one of {sorted(PROFILES)}")
    return PROFILES[code]

"""Caller-facing language profiles, selected with ``AGENT_LANGUAGE`` (default ``en``).

The prompts stay in English for every language (they are shared with upstream and
the model follows them fine); a non-English profile appends a directive telling the
agent to speak that language and how to adapt the English-specific speaking rules.
Each profile also carries defaults for the local (Phase 2 / MLX) voice slots;
explicit ``LOCAL_TTS_VOICE`` / ``LOCAL_STT_LANGUAGE`` env vars still win.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    stt_language: str  # label reported by the local STT (Qwen3-ASR auto-detects)
    kokoro_voice: str  # Kokoro voice ids are prefixed with their G2P lang code
    kokoro_lang_codes: str  # voice prefixes that fit this language
    instructions: str  # appended to COMMON_INSTRUCTIONS ("" = none)


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
- Tool arguments keep the formats the tools expect (ISO dates, Latin-letter emails, numbers as digits) - only the spoken reply is Chinese."""


PROFILES: dict[str, LanguageProfile] = {
    "en": LanguageProfile(
        code="en",
        stt_language="en",
        kokoro_voice="af_heart",
        kokoro_lang_codes="ab",
        instructions="",
    ),
    "zh": LanguageProfile(
        code="zh",
        stt_language="zh",
        kokoro_voice="zf_xiaobei",
        kokoro_lang_codes="z",
        instructions=_ZH_INSTRUCTIONS,
    ),
}


def current_language() -> LanguageProfile:
    code = os.getenv("AGENT_LANGUAGE", "en").strip().lower()
    if code not in PROFILES:
        raise ValueError(f"AGENT_LANGUAGE={code!r} is not one of {sorted(PROFILES)}")
    return PROFILES[code]

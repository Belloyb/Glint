"""ISO 639 language-code display names.

Media containers tag tracks with ISO 639-1 ("en") or ISO 639-2/B ("fre" —
the bibliographic code FFmpeg writes) language codes. This module maps the
common codes to English display names for menus and the info dialog, with no
external dependency. Unknown codes pass through uppercased — a code we
cannot name is still shown honestly (e.g. "QAA"), never dropped.
"""

from __future__ import annotations

# ISO 639-2/B (what FFmpeg/matroska usually write) plus the matching
# ISO 639-1 short forms, merged into one lookup.
_LANGUAGE_NAMES: dict[str, str] = {
    # 639-2/B and terminological variants
    "eng": "English",
    "fre": "French",
    "fra": "French",
    "ger": "German",
    "deu": "German",
    "jpn": "Japanese",
    "spa": "Spanish",
    "ita": "Italian",
    "por": "Portuguese",
    "rus": "Russian",
    "zho": "Chinese",
    "chi": "Chinese",
    "ara": "Arabic",
    "hin": "Hindi",
    "ben": "Bengali",
    "pun": "Punjabi",
    "guj": "Gujarati",
    "mar": "Marathi",
    "tam": "Tamil",
    "tel": "Telugu",
    "kan": "Kannada",
    "mal": "Malayalam",
    "urd": "Urdu",
    "fas": "Persian",
    "per": "Persian",
    "tur": "Turkish",
    "heb": "Hebrew",
    "yid": "Yiddish",
    "ell": "Greek",
    "gre": "Greek",
    "nld": "Dutch",
    "dut": "Dutch",
    "swe": "Swedish",
    "nor": "Norwegian",
    "dan": "Danish",
    "fin": "Finnish",
    "isl": "Icelandic",
    "pol": "Polish",
    "ces": "Czech",
    "cze": "Czech",
    "slk": "Slovak",
    "slo": "Slovak",
    "hun": "Hungarian",
    "ron": "Romanian",
    "rum": "Romanian",
    "bul": "Bulgarian",
    "ukr": "Ukrainian",
    "srp": "Serbian",
    "hrv": "Croatian",
    "bos": "Bosnian",
    "slv": "Slovenian",
    "mkd": "Macedonian",
    "sqi": "Albanian",
    "alb": "Albanian",
    "lit": "Lithuanian",
    "lav": "Latvian",
    "est": "Estonian",
    "kat": "Georgian",
    "geo": "Georgian",
    "hye": "Armenian",
    "arm": "Armenian",
    "aze": "Azerbaijani",
    "kaz": "Kazakh",
    "uzb": "Uzbek",
    "kir": "Kyrgyz",
    "tgk": "Tajik",
    "mon": "Mongolian",
    "tha": "Thai",
    "vie": "Vietnamese",
    "ind": "Indonesian",
    "msa": "Malay",
    "may": "Malay",
    "fil": "Filipino",
    "khm": "Khmer",
    "lao": "Lao",
    "mya": "Burmese",
    "amh": "Amharic",
    "hausa": "Hausa",
    "yor": "Yoruba",
    "ibo": "Igbo",
    "swa": "Swahili",
    "afr": "Afrikaans",
    "sot": "Sotho",
    "xho": "Xhosa",
    "zul": "Zulu",
    "korean": "Korean",  # defensive: "kor" below is the real code
    "kor": "Korean",
    "cat": "Catalan",
    "glg": "Galician",
    "eus": "Basque",
    "glk": "Gilaki",
    "bel": "Belarusian",
    "mai": "Maithili",
    "kok": "Konkani",
    "nep": "Nepali",
    "sin": "Sinhala",
    "tir": "Tigrinya",
    "som": "Somali",
    "run": "Rundi",
    "nya": "Chichewa",
    "mlg": "Malagasy",
    # Special matroska/FFmpeg markers
    "und": "Undetermined",
    "mul": "Multiple languages",
    "zxx": "No linguistic content",
    # Common ISO 639-1 short forms
    "en": "English",
    "fr": "French",
    "de": "German",
    "ja": "Japanese",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "zh": "Chinese",
    "ar": "Arabic",
    "hi": "Hindi",
    "tr": "Turkish",
    "ko": "Korean",
    "nl": "Dutch",
    "sv": "Swedish",
    "no": "Norwegian",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "el": "Greek",
    "he": "Hebrew",
    "hu": "Hungarian",
    "ro": "Romanian",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "ms": "Malay",
}


def language_display_name(code: str | None) -> str | None:
    """English display name for an ISO 639 language code.

    Returns ``None`` for ``None``/empty input; unknown codes are returned
    uppercased (still informative, never a lie).
    """
    if not code:
        return None
    key = code.strip().lower()
    if not key:
        return None
    return _LANGUAGE_NAMES.get(key, code.strip().upper())

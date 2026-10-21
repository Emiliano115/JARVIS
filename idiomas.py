"""Language metadata and best-effort detection shared by Jarvis voice and text."""
from __future__ import annotations

import re

LANGUAGES = {
    "es": "Español", "en": "English", "fr": "Français", "pt": "Português",
    "de": "Deutsch", "it": "Italiano", "zh-CN": "中文（简体）", "zh-TW": "中文（繁體）",
    "ja": "日本語", "ko": "한국어", "ar": "العربية", "hi": "हिन्दी",
    "ru": "Русский", "nl": "Nederlands", "tr": "Türkçe", "pl": "Polski",
    "sv": "Svenska", "da": "Dansk", "no": "Norsk", "fi": "Suomi",
    "el": "Ελληνικά", "he": "עברית", "uk": "Українська", "vi": "Tiếng Việt",
    "th": "ไทย", "id": "Bahasa Indonesia", "ms": "Bahasa Melayu", "ro": "Română",
    "hu": "Magyar", "cs": "Čeština", "ca": "Català", "bn": "বাংলা",
    "ta": "தமிழ்", "te": "తెలుగు", "ur": "اردو", "fa": "فارسی",
    "sw": "Kiswahili", "fil": "Filipino", "sr": "Српски", "hr": "Hrvatski",
    "bg": "Български", "sk": "Slovenčina", "sl": "Slovenščina", "af": "Afrikaans",
}

_ALIASES = {
    "zh": "zh-CN", "zh-hans": "zh-CN", "zh-hant": "zh-TW",
    "pt-br": "pt", "pt-pt": "pt", "en-us": "en", "en-gb": "en",
    "es-co": "es", "es-mx": "es", "fr-ca": "fr",
}


def normalize_language(code: str | None) -> str:
    value = str(code or "").strip().replace("_", "-")
    if value.lower() in {"auto", "automatic", "automático", "automatico"}:
        return "auto"
    alias = _ALIASES.get(value.lower())
    if alias:
        return alias
    if value in LANGUAGES:
        return value
    base = value.split("-", 1)[0].lower()
    if base in LANGUAGES:
        return base
    # Accept every language exposed by gTTS (when installed), so the UI can
    # offer the full voice catalog instead of an arbitrary short list.
    try:
        available = tts_language_codes()
        if value in available:
            return value
        if base in available:
            return base
    except Exception:
        pass
    return ""


def detect_language(text: str, fallback: str = "es") -> str:
    value = re.sub(r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", " ", str(text or ""))
    value = re.sub(r"<[^>]+>", " ", value).strip()
    words = set(re.findall(r"[a-záéíóúñüç]+", value.lower()))
    word_count = len(re.findall(r"\w+", value, flags=re.UNICODE))
    fallback_code = normalize_language(fallback) or "es"
    if word_count < 3:
        # Very short messages ("sí", "ok", names, typos) do not contain enough
        # evidence for a statistical language classifier. Keep the configured
        # interface/conversation language instead of guessing.
        return fallback_code

    # Spanish and Catalan are close enough that generic classifiers often
    # confuse short, informal Spanish. Resolve those cases using distinctive
    # words first; require multiple Catalan signals before switching to ca.
    spanish_markers = {
        "ahora", "aunque", "bastante", "bien", "cambiar", "cambio", "como",
        "cómo", "con", "cuando", "cuándo", "debería", "dime", "dónde", "entonces",
        "eres", "está", "están", "estaba", "estoy", "fue", "gracias", "gustaría",
        "hacer", "haces", "hola", "hoy", "igual", "me", "mucho", "muy", "necesito",
        "nos", "nunca", "para", "pero", "podrías", "puedes", "quiero", "sería",
        "también", "tengo", "tiene", "todo", "una", "uno", "ustedes", "voy", "ya",
        "osea", "o sea", "qué", "quién", "dime", "dijiste", "dijera",
        # Common function words keep short, typo-heavy Spanish prompts from
        # being misclassified when they contain film titles or model names.
        "que", "se", "sabe", "sobre", "y", "de", "del", "lo", "los",
        "las", "un", "una", "es", "son", "hay", "saber", "sabes",
        "funciona", "modelo", "modelos", "porque", "porqué",
    }
    catalan_markers = {
        "això", "aquesta", "aquest", "aquests", "aquestes", "amb", "avui",
        "demà", "doncs", "però", "perquè", "perque", "sóc", "ets", "som",
        "són", "vull", "vols", "puc", "pots", "podeu", "també", "molt",
        "gràcies", "sisplau", "siusplau", "llavors", "seva", "seu", "meva", "meu",
    }
    spanish_score = len(words & spanish_markers)
    catalan_score = len(words & catalan_markers)
    if "ñ" in value.lower() or "¿" in value or "¡" in value or spanish_score >= 2:
        return "es"
    if catalan_score >= 2 and catalan_score > spanish_score:
        return "ca"
    try:
        import langid
        detected, _confidence = langid.classify(value[:4000])
        code = normalize_language(detected)
        if code:
            if code == "ca" and catalan_score < 2:
                # Do not accept an isolated Catalan classification when the
                # text has no clear Catalan vocabulary; it is commonly a
                # Spanish false positive.
                return fallback_code
            return code
    except Exception:
        pass
    # Offline fallback for the most common languages if langid is not installed yet.
    hints = {
        "es": {"que", "qué", "para", "con", "como", "cómo", "pero", "está", "una", "por"},
        "en": {"the", "and", "you", "your", "what", "how", "with", "about", "please", "from"},
        "fr": {"les", "des", "une", "avec", "pour", "est", "pas", "vous", "comment", "bonjour"},
        "pt": {"não", "uma", "com", "para", "você", "está", "que", "como", "obrigado", "olá"},
        "de": {"der", "die", "das", "und", "nicht", "mit", "was", "wie", "eine", "ist"},
        "it": {"che", "non", "una", "con", "per", "come", "sono", "grazie", "ciao", "della"},
    }
    scores = {code: len(words & terms) for code, terms in hints.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else (normalize_language(fallback) or "es")


def language_name(code: str | None) -> str:
    normalized = normalize_language(code)
    if normalized in LANGUAGES:
        return LANGUAGES[normalized]
    try:
        from gtts.lang import tts_langs
        return tts_langs().get(normalized, "the user's language")
    except Exception:
        return LANGUAGES.get(normalized.split("-", 1)[0], "the user's language")


def tts_language_codes() -> set[str]:
    """Return the live language catalog from gTTS when installed; static fallback otherwise."""
    try:
        from gtts.lang import tts_langs
        return set(tts_langs())
    except Exception:
        return {code for code in LANGUAGES if len(code) <= 3} | {"zh-CN", "zh-TW"}


def available_languages() -> dict[str, str]:
    """Combine the readable built-in catalog with the installed gTTS catalog."""
    result = dict(LANGUAGES)
    try:
        from gtts.lang import tts_langs
        result.update({code: name for code, name in tts_langs().items()})
    except Exception:
        pass
    return result

"""Local language detection and application messages for English/Italian."""

import re
from functools import lru_cache
from typing import Literal

Language = Literal["en", "it"]
DocumentLanguage = Literal["en", "it", "mixed", "und"]
LANGUAGE_NAMES = {"en": "English", "it": "Italian"}
SUPPORTED_LANGUAGES = ("en", "it")

MESSAGES = {
    "out_of_scope": {
        "en": "Please ask about company financial or technical documents.",
        "it": "Fai una domanda sui documenti finanziari o tecnici dell'azienda.",
    },
    "insufficient_evidence": {
        "en": "The accessible documents do not provide enough evidence.",
        "it": "I documenti accessibili non contengono informazioni sufficienti.",
    },
    "session_locked": {
        "en": "Session locked after three out-of-scope questions",
        "it": "Sessione bloccata dopo tre domande fuori ambito",
    },
    "identity_ambiguous": {
        "en": "Multiple people match. Select a token and resend with identity_choices.",
        "it": (
            "Più persone corrispondono al nome. Seleziona un token e invia "
            "di nuovo la domanda con identity_choices."
        ),
    },
    "generation_failed": {
        "en": "Unable to produce an answer in the question's language. Please retry.",
        "it": "Impossibile generare una risposta nella lingua della domanda. Riprova.",
    },
}


@lru_cache(maxsize=1)
def detector():
    from lingua import Language, LanguageDetectorBuilder

    return (
        LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.ITALIAN)
        .with_minimum_relative_distance(0.15)
        .build()
    )


def detect_language(text: str, default: str = "en") -> str:
    # IDs, email addresses, and generated page headings are not language evidence.
    clean = re.sub(r"PII_[A-F0-9]{32}|[\w.+-]+@[\w.-]+|(?m:^## Page \d+\s*)", " ", text)
    clean = re.sub(r"\b[A-Z0-9_-]*\d[A-Z0-9_-]*\b", " ", clean, flags=re.I)
    clean = re.sub(
        r"\b(?:API|EBITDA|EUR|USD|GBP|HTTP|SQL|PDF|ROI|KPI|AI|euros?)\b",
        " ",
        clean,
        flags=re.I,
    )
    if not re.search(r"[^\W\d_]", clean, re.UNICODE):
        return default
    result = detector().detect_language_of(clean)
    return result.iso_code_639_1.name.lower() if result else default


def document_language(pages: list[tuple[int, str]]) -> str:
    # Inspect paragraphs too: a bilingual page must not be labelled monolingual.
    languages = {
        detect_language(part, default="und")
        for _, text in pages
        for part in re.split(r"\n+", text)
        if part.strip()
    }
    languages.discard("und")
    return "mixed" if len(languages) > 1 else next(iter(languages), "und")


def message(key: str, language: str) -> str:
    return MESSAGES[key][language]

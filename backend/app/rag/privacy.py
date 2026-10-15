import re
from uuid import uuid4

from fastapi import HTTPException

from app.rag.language import SUPPORTED_LANGUAGES, detect_language, message
from app.rag.models import Principal
from app.rag.store import Store, normalized

TOKEN_RE = re.compile(r"PII_[A-F0-9]{32}")


class Privacy:
    def __init__(self, store: Store, analyzer=None):
        self.store = store
        if analyzer is None:
            from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
            from presidio_analyzer.nlp_engine import SpacyNlpEngine
            from presidio_analyzer.predefined_recognizers import (
                CreditCardRecognizer,
                EmailRecognizer,
                IbanRecognizer,
                IpRecognizer,
                PhoneRecognizer,
            )

            engine = SpacyNlpEngine(
                models=[
                    {"lang_code": "en", "model_name": "en_core_web_lg"},
                    {"lang_code": "it", "model_name": "it_core_news_lg"},
                ]
            )
            analyzer = AnalyzerEngine(
                nlp_engine=engine, supported_languages=list(SUPPORTED_LANGUAGES)
            )
            for language in SUPPORTED_LANGUAGES:
                # Explicitly cover shared identifiers in both language pipelines.
                for recognizer in (
                    EmailRecognizer,
                    IbanRecognizer,
                    CreditCardRecognizer,
                    IpRecognizer,
                ):
                    analyzer.registry.add_recognizer(
                        recognizer(supported_language=language)
                    )
                analyzer.registry.add_recognizer(
                    PhoneRecognizer(
                        supported_language=language,
                        supported_regions=["IT", "US", "GB"],
                    )
                )
                analyzer.registry.add_recognizer(
                    PatternRecognizer(
                        supported_entity="EMPLOYEE_ID",
                        supported_language=language,
                        patterns=[
                            Pattern(
                                "employee_id", r"\b(?:EMP|EID)[-:]?\s*\d{3,12}\b", 0.9
                            )
                        ],
                    )
                )
        self.analyzer = analyzer
        self.languages = tuple(
            getattr(analyzer, "supported_languages", SUPPORTED_LANGUAGES)
        )

    def pseudonymize(
        self,
        text: str,
        p: Principal,
        document_id: str | None = None,
        choices: dict[str, str] | None = None,
        language: str | None = None,
    ) -> str:
        choices = {normalized(k): v for k, v in (choices or {}).items()}
        identities = self.store.allowed_identities(p)
        by_alias: dict[str, list[dict]] = {}
        for identity in identities:
            # Only curated identities may link names across documents at ingestion.
            if document_id and not identity.get("curated", False):
                continue
            for alias in identity["aliases"]:
                by_alias.setdefault(normalized(alias), []).append(identity)
        replacements = []
        protected = [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
        for alias in sorted(by_alias, key=len, reverse=True):
            if not alias:
                continue
            candidates = {
                i["token"]: i
                for i in self.store.lookup_alias(p, alias)
                if not document_id or i.get("curated", False)
            }
            for match in re.finditer(
                r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I
            ):
                start, end = match.span()
                if any(start < b and end > a for a, b in protected):
                    continue
                selected = choices.get(alias)
                if selected is not None and selected not in candidates:
                    raise HTTPException(403, "Identity selection is not authorized")
                if len(candidates) > 1 and selected is None:
                    raise HTTPException(
                        409,
                        {
                            "code": "identity_ambiguous",
                            "message": message(
                                "identity_ambiguous", language or detect_language(text)
                            ),
                            "alias": match[0],
                            "candidates": [
                                {
                                    "token": token,
                                    **(
                                        {"name": i["name"]}
                                        if "pii:read" in p.scopes
                                        else {}
                                    ),
                                }
                                for token, i in candidates.items()
                            ],
                        },
                    )
                token = selected or next(iter(candidates))
                replacements.append((start, end, token))
                protected.append((start, end))
                if document_id:
                    with self.store.db() as db:
                        db.execute(
                            "INSERT OR IGNORE INTO mentions VALUES(?,?)",
                            (token, document_id),
                        )
        # Scan through both NER models, even for a predominantly monolingual page.
        # This covers names/identifiers in mixed-language tables and queries.
        detections = [
            entity
            for lang in self.languages
            for entity in self.analyzer.analyze(
                text=text,
                language=lang,
                entities=[
                    "PERSON",
                    "EMAIL_ADDRESS",
                    "PHONE_NUMBER",
                    "CREDIT_CARD",
                    "IBAN_CODE",
                    "US_SSN",
                    "US_PASSPORT",
                    "IP_ADDRESS",
                    "EMPLOYEE_ID",
                    "IT_FISCAL_CODE",
                    "IT_VAT_CODE",
                    "IT_IDENTITY_CARD",
                    "IT_PASSPORT",
                ],
                score_threshold=0.4,
            )
        ]
        # Resolve overlapping recognizers by confidence, then length.
        for entity in sorted(detections, key=lambda e: (-e.score, -(e.end - e.start))):
            start, end = entity.start, entity.end
            if any(start < b and end > a for a, b in protected):
                continue
            value = text[start:end]
            if document_id:
                strong = (
                    f"observed:{entity.entity_type}:{value}"
                    if entity.entity_type in {"EMAIL_ADDRESS", "EMPLOYEE_ID"}
                    else f"mention:{document_id}:{entity.entity_type}:{value}"
                )
                token = self.store.put_identity(p, strong, value, [], [], document_id)
            else:
                # Keep unknown question entities ephemeral.
                token = "PII_" + uuid4().hex.upper()
            replacements.append((start, end, token))
            protected.append((start, end))
        for start, end, token in sorted(replacements, reverse=True):
            text = text[:start] + token + text[end:]
        return text

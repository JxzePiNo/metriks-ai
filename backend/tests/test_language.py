import sqlite3

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.rag.extraction import classify
from app.rag.language import detect_language, document_language
from app.rag.models import Principal
from app.rag.store import Store


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What was company revenue?", "en"),
        ("Quali sono i ricavi dell'azienda?", "it"),
        ("Mostra il bilancio aziendale", "it"),
        ("How does the API work?", "en"),
        ("Come funziona il sistema?", "it"),
        ("ricavi", "it"),
        ("revenue", "en"),
        ("API?", "en"),
        ("EUR 100", "en"),
        ("PII_" + "A" * 32, "en"),
        ("## Page 1\nRicavi EUR 100", "it"),
    ],
)
def test_local_query_language(text, expected):
    assert detect_language(text) == expected


def test_language_neutral_query_uses_configured_fallback():
    assert detect_language("EBITDA?", default="it") == "it"
    assert detect_language("API?", default="und") == "und"


def test_mixed_document_language():
    assert (
        document_language(
            [(1, "Revenue was 100 euros."), (2, "I ricavi sono stati pari a 100 euro.")]
        )
        == "mixed"
    )
    assert (
        document_language(
            [(1, "Revenue was 100 euros.\nI ricavi sono stati pari a 100 euro.")]
        )
        == "mixed"
    )
    assert document_language([(1, "PII_" + "A" * 32)]) == "und"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Il bilancio riporta ricavi e passività", "financial"),
        ("Architettura e configurazione dell'infrastruttura", "technical"),
        ("Ricavi e costi per l'architettura software", "mixed"),
        ("Financial revenue and architettura tecnica", "mixed"),
        ("Verbale della riunione", "other"),
    ],
)
def test_bilingual_classification(text, expected):
    assert classify(text) == expected


def test_old_private_database_migrates_without_losing_records(tmp_path):
    with sqlite3.connect(tmp_path / "private.sqlite3") as db:
        db.execute(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, "
            "owner TEXT NOT NULL, readers TEXT NOT NULL, title TEXT NOT NULL, "
            "classification TEXT NOT NULL, confidentiality TEXT NOT NULL, "
            "status TEXT NOT NULL, pages INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "old-doc",
                "acme",
                "alice",
                '["alice"]',
                "Old document",
                "financial",
                "confidential",
                "ready",
                1,
            ),
        )
    key = Fernet.generate_key().decode()
    store = Store(tmp_path, key, "k" * 64, 3600)
    p = Principal(tenant_id="acme", user_id="alice")
    assert store.document(p, "old-doc")["language"] == "und"
    store.create_document(p, "new-doc", ["alice"], "financial", "confidential", 1, "it")
    store.status("new-doc", "ready")
    assert store.document(p, "new-doc")["language"] == "it"
    # Startup migration is idempotent.
    assert len(Store(tmp_path, key, "k" * 64, 3600).visible_docs(p)) == 2


def test_bilingual_defaults_and_model_upgrade():
    settings = Settings(_env_file=None)
    assert settings.ocr_language == "eng+ita"
    assert "multilingual" in settings.embedding_model
    assert "mmarco" in settings.reranker_model
    assert settings.elasticsearch_index == "metriks-chunks-multilingual-v2"


def test_pdf_ocr_uses_both_language_packs(monkeypatch):
    import sys
    from types import SimpleNamespace

    from app.rag.extraction import extract_pdf

    calls = []

    class Page:
        def get_text(self, *args, **kwargs):
            return "I ricavi sono pari a 100 euro" if "textpage" in kwargs else ""

        def get_images(self):
            return ["embedded-image"]

        def get_textpage_ocr(self, **kwargs):
            calls.append(kwargs)
            return "ocr-text-page"

        def find_tables(self):
            return SimpleNamespace(tables=[])

    class PDF(list):
        needs_pass = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(
        sys.modules, "pymupdf", SimpleNamespace(open=lambda **_: PDF([Page()]))
    )
    pages = extract_pdf(b"%PDF-test", Settings())
    assert calls[0]["language"] == "eng+ita"
    assert "ricavi" in pages[0][1]


@pytest.mark.parametrize(
    ("old_model", "old_schema"),
    [
        ("sentence-transformers/all-mpnet-base-v2", "en-it-v2"),
        ("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", None),
    ],
)
def test_old_index_rejected_even_with_matching_vector_dimensions(
    monkeypatch, old_model, old_schema
):
    import sys
    from types import SimpleNamespace

    from app.rag.retrieval import Search

    mapping = {
        "chunks": {
            "mappings": {
                "_meta": {"embedding_model": old_model, "retrieval_schema": old_schema},
                "properties": {"vector": {"dims": 768}},
            }
        }
    }
    indices = SimpleNamespace(exists=lambda **_: True, get_mapping=lambda **_: mapping)
    monkeypatch.setitem(
        sys.modules,
        "elasticsearch",
        SimpleNamespace(Elasticsearch=lambda *a, **k: SimpleNamespace(indices=indices)),
    )
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(
            SentenceTransformer=lambda *a, **k: SimpleNamespace(
                get_sentence_embedding_dimension=lambda: 768
            ),
            CrossEncoder=lambda *a, **k: object(),
        ),
    )
    with pytest.raises(ValueError, match="use a new index"):
        Search(Settings())

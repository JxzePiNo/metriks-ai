import json
import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.rag.extraction import chunk_pages, classify, extract_pdf
from app.rag.generation import ScopeRail
from app.rag.models import (
    Evidence,
    GeneratedAnswer,
    GeneratedClaim,
    IdentityInput,
    Principal,
    Question,
)
from app.rag.privacy import Privacy
from app.rag.retrieval import Search, rrf
from app.rag.service import RAGService
from app.rag.store import Store


class Analyzer:
    def analyze(self, text, **kwargs):
        results = []
        for entity, pattern in [
            ("EMAIL_ADDRESS", r"[\w.]+@[\w.]+"),
            ("PERSON", r"\b(?:Chandana Sree Mala|Chandana|Alice Smith)\b"),
        ]:
            for match in re.finditer(pattern, text):
                results.append(
                    SimpleNamespace(
                        start=match.start(),
                        end=match.end(),
                        score=0.9,
                        entity_type=entity,
                    )
                )
        return results


class Tokenizer:
    def encode(self, text, **kwargs):
        return text.split()


class FakeSearch:
    encoder = SimpleNamespace(tokenizer=Tokenizer(), max_seq_length=128)

    def __init__(self):
        self.chunks = []
        self.questions = []
        self.fail = False

    def index_chunks(self, chunks):
        self.chunks.extend(chunks)
        if self.fail:
            raise RuntimeError("index unavailable")

    def delete(self, tenant, document_id):
        self.chunks = [c for c in self.chunks if c["document_id"] != document_id]

    def retrieve(self, question, p, doc_ids, labels, top_k):
        self.questions.append(question)
        return [
            {"_id": c["id"], "_source": c}
            for c in self.chunks
            if c["tenant_id"] == p.tenant_id
            and c["document_id"] in doc_ids
            and p.user_id in c["allowed_users"]
        ][:top_k]


class Generator:
    def __init__(self):
        self.calls = []
        self.bad_quote = False

    def answer(self, question, passages, language="en"):
        self.calls.append((question, passages))
        return GeneratedAnswer(
            claims=[
                GeneratedClaim(
                    text="<script>revenue</script>",
                    evidence=[
                        Evidence(
                            source_id="S1",
                            quote=(
                                "invented" if self.bad_quote else passages[0]["text"]
                            ),
                        )
                    ],
                )
            ]
        )


class Rail:
    def __init__(self):
        self.allowed = True
        self.questions = []

    def allows(self, question):
        self.questions.append(question)
        return self.allowed


@pytest.fixture
def system(tmp_path, monkeypatch):
    settings = Settings(
        app_env="test",
        rag_enabled=True,
        rag_data_dir=tmp_path,
        identity_encryption_key=Fernet.generate_key().decode(),
        identity_lookup_key="k" * 64,
        rag_api_tokens=json.dumps(
            {
                "test-token": {
                    "tenant_id": "acme",
                    "user_id": "alice",
                    "scopes": [
                        "documents:read",
                        "documents:write",
                        "chat:write",
                        "identity:write",
                        "pii:read",
                    ],
                }
            }
        ),
    )
    store = Store(
        tmp_path,
        settings.identity_encryption_key.get_secret_value(),
        settings.identity_lookup_key.get_secret_value(),
        3600,
    )
    search, generator, rail = FakeSearch(), Generator(), Rail()
    svc = RAGService(
        settings, store, Privacy(store, Analyzer()), search, generator, rail
    )
    monkeypatch.setattr(
        "app.rag.service.extract_pdf",
        lambda data, settings: [
            (1, "## Page 1\nChandana revenue is EUR 100; contact chandana@example.com")
        ],
    )
    p = Principal(
        tenant_id="acme",
        user_id="alice",
        scopes={
            "documents:read",
            "documents:write",
            "chat:write",
            "identity:write",
            "pii:read",
        },
    )
    return svc, p


def ingest(svc, p):
    return svc.ingest(p, b"%PDF-test", [], "confidential")


def question(svc, p, **kwargs):
    return Question(
        session_id=svc.store.new_session(p)["session_id"],
        question="What is Chandana's revenue?",
        **kwargs,
    )


def test_no_original_pii_in_markdown_index_or_private_db(system):
    svc, p = system
    doc = ingest(svc, p)
    markdown = (svc.markdown_dir / f"{doc['id']}.md").read_text()
    assert "Chandana" not in markdown and "chandana@example.com" not in markdown
    assert "PII_" in markdown
    assert all("Chandana" not in c["text"] for c in svc.search.chunks)
    assert doc["classification"] == "financial"
    with svc.store.db() as db:
        dump = "\n".join(db.iterdump())
    assert "Chandana" not in dump and "chandana@example.com" not in dump


def test_query_is_sanitized_before_rail_search_and_generation(system):
    svc, p = system
    ingest(svc, p)
    answer = svc.ask(p, question(svc, p))
    assert answer["status"] == "answered"
    assert "Chandana" not in svc.rail.questions[-1]
    assert "Chandana" not in svc.search.questions[-1]
    assert "Chandana" not in str(svc.generator.calls)
    assert "<mark>" in answer["answer_html"]
    assert "<script>" not in answer["answer_html"]
    assert "&lt;script&gt;" in answer["answer_html"]
    assert answer["citations"][0]["page"] == 1


def test_ambiguous_names_require_explicit_authorized_selection(system):
    svc, p = system
    first = svc.register_identity(
        p,
        IdentityInput(
            identifier="a@example.com",
            identifier_type="email",
            canonical_name="Chandana Sree Mala",
            aliases=["Chandana"],
        ),
    )
    svc.register_identity(
        p,
        IdentityInput(
            identifier="b@example.com",
            identifier_type="email",
            canonical_name="Chandana Rao",
            aliases=["Chandana"],
        ),
    )
    with pytest.raises(HTTPException) as exc:
        svc.privacy.pseudonymize("Chandana revenue", p)
    assert exc.value.status_code == 409
    assert len(exc.value.detail["candidates"]) == 2
    assert (
        svc.privacy.pseudonymize(
            "Chandana revenue", p, choices={"Chandana": first["token"]}
        )
        == f"{first['token']} revenue"
    )
    with pytest.raises(HTTPException) as exc:
        svc.privacy.pseudonymize(
            "Chandana revenue", p, choices={"Chandana": "unauthorized-token"}
        )
    assert exc.value.status_code == 403


def test_name_only_mentions_not_merged_between_documents(system):
    svc, p = system
    ingest(svc, p)
    ingest(svc, p)
    with pytest.raises(HTTPException) as exc:
        svc.privacy.pseudonymize("Chandana", p)
    assert exc.value.status_code == 409
    # Email is a strong identifier; the name remains two separate entities.
    assert len(svc.store.allowed_identities(p)) == 3


def test_curated_aliases_share_a_token_and_longest_match_wins(system):
    svc, p = system
    token = svc.register_identity(
        p,
        IdentityInput(
            identifier="EMP-1234",
            identifier_type="employee_id",
            canonical_name="Chandana Sree Mala",
            aliases=["Chandana", "C. S. Mala"],
        ),
    )["token"]
    doc = ingest(svc, p)
    for alias in ["Chandana Sree Mala", "Chandana", "C. S. Mala", "EMP-1234"]:
        assert svc.privacy.pseudonymize(alias, p) == token
    assert token in (svc.markdown_dir / f"{doc['id']}.md").read_text()


def test_tenant_document_identity_and_session_isolation(system):
    svc, p = system
    doc = ingest(svc, p)
    sid = svc.store.new_session(p)["session_id"]
    for other in [
        Principal(tenant_id="other", user_id="alice"),
        Principal(tenant_id="acme", user_id="bob"),
    ]:
        assert svc.store.visible_docs(other) == []
        assert svc.store.allowed_identities(other) == []
        with pytest.raises(HTTPException):
            svc.store.document(other, doc["id"])
        with pytest.raises(HTTPException):
            svc.store.session(other, sid)


def test_restoration_requires_scope_and_only_restores_retrieved_tokens(system):
    svc, p = system
    ingest(svc, p)
    answer = svc.ask(p, question(svc, p, restore_pii=True))
    assert "Chandana" in answer["citations"][0]["excerpt"]
    token = svc.register_identity(
        p,
        IdentityInput(
            identifier="hidden@example.com",
            identifier_type="email",
            canonical_name="Unretrieved Person",
        ),
    )["token"]
    assert svc.store.restore(token, p, set()) == token
    p.scopes.remove("pii:read")
    with pytest.raises(HTTPException) as exc:
        svc.ask(p, question(svc, p, restore_pii=True))
    assert exc.value.status_code == 403


def test_unsupported_quotes_discarded(system):
    svc, p = system
    ingest(svc, p)
    svc.generator.bad_quote = True
    answer = svc.ask(p, question(svc, p))
    assert answer["status"] == "insufficient_evidence"
    assert answer["citations"] == []


def test_three_scope_attempts_persist_and_do_not_run_generation(system):
    svc, p = system
    svc.rail.allowed = False
    q = question(svc, p)
    for remaining in [2, 1, 0]:
        answer = svc.ask(p, q)
        assert answer["attempts_remaining"] == remaining
    assert answer["locked"]
    assert not svc.generator.calls and not svc.search.questions
    with pytest.raises(HTTPException) as exc:
        svc.ask(p, q)
    assert exc.value.status_code == 423
    reopened = Store(
        svc.settings.rag_data_dir,
        svc.settings.identity_encryption_key.get_secret_value(),
        svc.settings.identity_lookup_key.get_secret_value(),
        3600,
    )
    with pytest.raises(HTTPException) as exc:
        reopened.session(p, q.session_id)
    assert exc.value.status_code == 423


def test_atomic_attempt_counter_under_concurrency(system):
    svc, p = system
    sid = svc.store.new_session(p)["session_id"]

    def reject(_):
        try:
            return svc.store.session(p, sid, reject=True)["attempts"]
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reject, range(8)))
    assert sorted(results) == [1, 2, 3, 423, 423, 423, 423, 423]


def test_failed_ingestion_hidden_from_search(system):
    svc, p = system
    svc.search.fail = True
    with pytest.raises(RuntimeError):
        ingest(svc, p)
    assert svc.store.visible_docs(p) == []
    assert list(svc.markdown_dir.iterdir()) == []
    assert svc.ask(p, question(svc, p))["status"] == "insufficient_evidence"


def test_api_auth_upload_and_error_contract(system):
    svc, p = system
    app = create_app(svc.settings)
    app.state.rag_service = svc
    with TestClient(app) as client:
        assert client.get("/api/v1/documents").status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        response = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("private-name.pdf", b"%PDF-test", "application/pdf")},
        )
        assert response.status_code == 201
        doc_id = response.json()["id"]
        assert "private-name" not in response.text
        markdown = client.get(f"/api/v1/documents/{doc_id}/markdown", headers=headers)
        assert markdown.status_code == 200 and "Chandana" not in markdown.text
        assert (
            client.post(
                "/api/v1/documents",
                headers=headers,
                files={"file": ("x.pdf", b"x")},
                data={"allowed_users": "bad"},
            ).status_code
            == 422
        )
        assert (
            client.delete(f"/api/v1/documents/{doc_id}", headers=headers).status_code
            == 204
        )
        assert (
            client.get(f"/api/v1/documents/{doc_id}", headers=headers).status_code
            == 404
        )


def test_rrf_and_page_aware_chunking():
    assert rrf([[{"_id": "a"}, {"_id": "b"}], [{"_id": "b"}]])[0]["_id"] == "b"
    chunks = chunk_pages(
        [(1, "one two three four five"), (2, "six seven")],
        Tokenizer(),
        size=3,
        overlap=1,
    )
    assert chunks == [
        {"page": 1, "text": "one two three"},
        {"page": 1, "text": "three four five"},
        {"page": 2, "text": "six seven"},
    ]
    assert classify("API revenue architecture") == "mixed"


def test_elastic_filters_both_retrievers_before_fusion():
    from threading import Lock

    calls = []
    search = Search.__new__(Search)
    search.index = "chunks"
    search.lock = Lock()
    search.encoder = SimpleNamespace(
        encode=lambda *a, **k: SimpleNamespace(tolist=lambda: [0.1] * 3)
    )

    def run(**kwargs):
        calls.append(kwargs)
        return {"hits": {"hits": []}}

    search.client = SimpleNamespace(search=run)
    p = Principal(tenant_id="tenant-1", user_id="alice")
    assert search.retrieve("budget", p, ["document-1"], ["financial"], 5) == []
    filters = calls[0]["query"]["bool"]["filter"]
    assert calls[0]["query"]["bool"]["must"][0]["multi_match"]["fields"] == [
        "text",
        "text.en",
        "text.it",
    ]
    assert filters == calls[1]["knn"]["filter"]["bool"]["filter"]
    assert {"term": {"tenant_id": "tenant-1"}} in filters
    assert {"term": {"allowed_users": "alice"}} in filters
    assert {"terms": {"document_id": ["document-1"]}} in filters


def test_real_pymupdf_extraction(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Revenue EUR 100")
        data = doc.tobytes()
    pages = extract_pdf(data, Settings(ocr_enabled=False))
    assert pages[0][0] == 1 and "Revenue EUR 100" in pages[0][1]
    with pytest.raises(HTTPException) as exc:
        extract_pdf(b"not a PDF", Settings())
    assert exc.value.status_code == 415


def test_real_nemo_input_rail_without_api_calls():
    pytest.importorskip("nemoguardrails")
    generator = SimpleNamespace(
        in_scope=lambda question: "revenue" in question or "ricavi" in question
    )
    rail = ScopeRail(generator)
    assert rail.allows("What was company revenue?") is True
    assert rail.allows("Tell me a joke") is False
    assert rail.allows("Quali sono i ricavi dell'azienda?") is True
    assert rail.allows("Raccontami una barzelletta") is False


def test_real_presidio_analyzer_with_local_spacy_pipeline(system, tmp_path):
    spacy = pytest.importorskip("spacy")
    presidio = pytest.importorskip("presidio_analyzer")
    from presidio_analyzer.nlp_engine import SpacyNlpEngine

    # Deterministic local NER fixture, without downloading a public language model.
    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns([{"label": "PERSON", "pattern": "Chandana Sree Mala"}])
    path = tmp_path / "test-spacy"
    nlp.to_disk(path)
    engine = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": str(path)}])
    analyzer = presidio.AnalyzerEngine(nlp_engine=engine, supported_languages=["en"])
    svc, p = system
    privacy = Privacy(svc.store, analyzer)
    safe = privacy.pseudonymize("Chandana Sree Mala: chandana@example.com", p)
    assert "Chandana" not in safe and "chandana@example.com" not in safe
    assert len(re.findall(r"PII_[A-F0-9]{32}", safe)) == 2


def test_rail_failure_does_not_consume_attempts(system):
    svc, p = system
    q = question(svc, p)

    def fail(_):
        raise RuntimeError("provider unavailable")

    svc.rail.allows = fail
    with pytest.raises(RuntimeError):
        svc.ask(p, q)
    assert svc.store.session(p, q.session_id)["attempts"] == 0


def test_no_generation_for_unauthorized_search_hit(system):
    svc, p = system
    ingest(svc, p)
    # Even a search provider returning a forbidden document cannot pass the DB check.
    svc.search.chunks[0]["document_id"] = "forbidden-document"
    svc.search.retrieve = lambda *args: [
        {"_id": "forbidden", "_source": svc.search.chunks[0]}
    ]
    assert svc.ask(p, question(svc, p))["status"] == "insufficient_evidence"
    assert svc.generator.calls == []


@pytest.mark.parametrize(
    ("language", "question", "claim_text"),
    [
        ("en", "What was company revenue?", "Company revenue was 100 euros."),
        ("it", "Quali sono i ricavi?", "I ricavi ammontano a 100 euro."),
    ],
)
def test_real_openai_sdk_structured_response_and_strict_schema(
    language, question, claim_text
):
    openai = pytest.importorskip("openai")
    import httpx

    from app.rag.generation import Generator

    requests = []

    def check_schema(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check_schema(value)
        elif isinstance(node, list):
            for value in node:
                check_schema(value)

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["store"] is False
        check_schema(payload["text"]["format"]["schema"])
        result = (
            {"allowed": True}
            if payload["text"]["format"]["name"] == "ScopeDecision"
            else {
                "claims": [
                    {
                        "text": claim_text,
                        "evidence": [{"source_id": "S1", "quote": "Revenue 100"}],
                    }
                ]
            }
        )
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "test-model",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(result),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    generator = Generator.__new__(Generator)
    generator.model = "test-model"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        generator.client = openai.OpenAI(api_key="test-placeholder", http_client=client)
        assert generator.in_scope(question) is True
        response = generator.answer(
            question,
            [{"source_id": "S1", "text": "Revenue 100"}],
            language=language,
        )
    assert response.claims[0].evidence[0].quote == "Revenue 100"
    assert response.claims[0].text == claim_text
    assert ("Italian" if language == "it" else "English") in requests[-1]["input"][0][
        "content"
    ]
    assert len(requests) == 2


def test_italian_refusal_lock_and_insufficient_evidence(system):
    svc, p = system
    q = Question(
        session_id=svc.store.new_session(p)["session_id"],
        question="Quali sono i ricavi dell'azienda?",
    )
    answer = svc.ask(p, q)
    assert answer["language"] == "it"
    assert answer["status"] == "insufficient_evidence"
    assert (
        answer["answer"]
        == "I documenti accessibili non contengono informazioni sufficienti."
    )
    svc.rail.allowed = False
    for remaining in [2, 1, 0]:
        answer = svc.ask(p, q)
        assert answer["language"] == "it"
        assert answer["attempts_remaining"] == remaining
        assert answer["answer"].startswith("Fai una domanda")
    with pytest.raises(HTTPException) as exc:
        svc.ask(p, q)
    assert exc.value.status_code == 423
    assert "Sessione bloccata" in exc.value.detail


def test_api_language_hint_for_ambiguous_queries(system):
    svc, p = system
    app = create_app(svc.settings)
    app.state.rag_service = svc
    sid = svc.store.new_session(p)["session_id"]
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": "Bearer test-token"},
            json={"session_id": sid, "question": "API?", "language": "it"},
        )
    assert response.status_code == 200
    assert response.json()["language"] == "it"
    assert response.json()["answer"].startswith("I documenti accessibili")


def test_bilingual_document_language_and_model_chunk_limit(system, monkeypatch):
    svc, p = system
    monkeypatch.setattr(
        "app.rag.service.extract_pdf",
        lambda *_: [
            (
                1,
                "## Page 1\nIl bilancio riporta ricavi di 100 euro. " + "ricavi " * 200,
            ),
            (2, "## Page 2\nThe company software architecture is described here."),
        ],
    )
    doc = ingest(svc, p)
    assert doc["language"] == "mixed"
    assert doc["classification"] == "mixed"
    assert {c["language"] for c in svc.search.chunks} == {"en", "it"}
    assert all(len(c["text"].split()) <= 112 for c in svc.search.chunks)


@pytest.mark.parametrize(
    ("query", "language", "source_text", "claim_text"),
    [
        (
            "Quali sono i ricavi?",
            "it",
            "Revenue was EUR 100.",
            "I ricavi ammontano a 100 euro.",
        ),
        (
            "What was company revenue?",
            "en",
            "I ricavi ammontano a 100 euro.",
            "Company revenue was 100 euros.",
        ),
    ],
)
def test_response_language_independent_of_source_language(
    system,
    monkeypatch,
    query,
    language,
    source_text,
    claim_text,
):
    svc, p = system
    monkeypatch.setattr("app.rag.service.extract_pdf", lambda *_: [(1, source_text)])
    ingest(svc, p)

    def answer(question, passages, language):
        assert question == query
        assert language == ("it" if query.startswith("Quali") else "en")
        return GeneratedAnswer(
            claims=[
                GeneratedClaim(
                    text=claim_text,
                    evidence=[Evidence(source_id="S1", quote=passages[0]["text"])],
                )
            ]
        )

    svc.generator.answer = answer
    result = svc.ask(
        p, Question(session_id=svc.store.new_session(p)["session_id"], question=query)
    )
    assert result["language"] == language
    assert result["answer"].startswith(claim_text)
    assert result["claims"][0]["quotes"]["S1"] == source_text
    assert f"<mark>{source_text}</mark>" in result["answer_html"]


def test_real_bilingual_presidio_including_italian_identifiers(
    system, tmp_path, monkeypatch
):
    spacy = pytest.importorskip("spacy")
    pytest.importorskip("presidio_analyzer")
    from presidio_analyzer.nlp_engine import SpacyNlpEngine

    models = []
    for lang, name, label in [
        ("en", "Alice Smith", "PERSON"),
        ("it", "Mario Rossi", "PER"),
    ]:
        nlp = spacy.blank(lang)
        nlp.add_pipe("entity_ruler").add_patterns([{"label": label, "pattern": name}])
        path = tmp_path / f"spacy-{lang}"
        nlp.to_disk(path)
        models.append({"lang_code": lang, "model_name": str(path)})
    engine = SpacyNlpEngine(models=models)
    # Exercise the production registry setup; replace only downloaded NER weights.
    monkeypatch.setattr(
        "presidio_analyzer.nlp_engine.SpacyNlpEngine", lambda **_: engine
    )
    svc, p = system
    privacy = Privacy(svc.store)
    raw = (
        "Alice Smith and Mario Rossi; codice fiscale RSSMRA85T10A562S; "
        "partita IVA 12345678903; email mario@example.com; "
        "IBAN IT60X0542811101000000123456; EMP-1234"
    )
    safe = privacy.pseudonymize(raw, p)
    for value in (
        "Alice Smith",
        "Mario Rossi",
        "RSSMRA85T10A562S",
        "12345678903",
        "mario@example.com",
        "IT60X0542811101000000123456",
        "EMP-1234",
    ):
        assert value not in safe
    assert privacy.languages == ("en", "it")


@pytest.mark.parametrize(
    ("language", "wrong", "correct"),
    [
        (
            "it",
            "The company's revenue was 100 euros.",
            "I ricavi ammontano a 100 euro.",
        ),
        (
            "en",
            "I ricavi ammontano a 100 euro.",
            "The company's revenue was 100 euros.",
        ),
    ],
)
def test_generator_retries_wrong_language_and_preserves_original_quotes(
    language, wrong, correct
):
    from app.rag.generation import Generator

    requests = []

    def parse(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            output_parsed=GeneratedAnswer(
                claims=[
                    GeneratedClaim(
                        text=wrong if len(requests) == 1 else correct,
                        evidence=[
                            Evidence(source_id="S1", quote="Revenue was EUR 100.")
                        ],
                    )
                ]
            )
        )

    generator = Generator.__new__(Generator)
    generator.model = "test-model"
    generator.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    answer = generator.answer(
        "revenue?",
        [{"source_id": "S1", "text": "Revenue was EUR 100."}],
        language=language,
    )
    assert len(requests) == 2
    assert "Retry" in requests[1]["input"][0]["content"]
    assert answer.claims[0].text == correct
    assert answer.claims[0].evidence[0].quote == "Revenue was EUR 100."


def test_generator_fails_closed_after_two_wrong_language_answers():
    from app.rag.generation import Generator

    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=GeneratedAnswer(
                claims=[
                    GeneratedClaim(
                        text="The company's revenue was 100 euros.", evidence=[]
                    )
                ]
            )
        )

    generator = Generator.__new__(Generator)
    generator.model = "test-model"
    generator.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(HTTPException) as exc:
        generator.answer("Quali sono i ricavi?", [], language="it")
    assert len(calls) == 2
    assert exc.value.status_code == 503
    assert "lingua della domanda" in exc.value.detail


def test_switching_query_language_does_not_reset_attempts(system):
    svc, p = system
    svc.rail.allowed = False
    sid = svc.store.new_session(p)["session_id"]
    for query, language, count in [
        ("Tell me a joke", "en", 1),
        ("Raccontami una barzelletta", "it", 2),
    ]:
        result = svc.ask(p, Question(session_id=sid, question=query))
        assert result["language"] == language
        assert result["attempts"] == count

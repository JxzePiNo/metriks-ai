import html
import json
import logging
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException

from app.rag.extraction import chunk_pages, classify, extract_pdf
from app.rag.language import detect_language, document_language, message
from app.rag.models import IdentityInput, Principal, Question
from app.rag.privacy import TOKEN_RE, Privacy
from app.rag.store import Store


class RAGService:
    def __init__(
        self, settings, store=None, privacy=None, search=None, generator=None, rail=None
    ):
        self.settings = settings
        # NeMo's INFO event trace includes user messages. Keep content out of logs.
        for package in ("nemoguardrails", "presidio-analyzer", "openai"):
            logging.getLogger(package).setLevel(logging.WARNING)
        self.store = store or Store(
            settings.rag_data_dir,
            settings.identity_encryption_key.get_secret_value(),
            settings.identity_lookup_key.get_secret_value(),
            settings.session_ttl_seconds,
        )
        self.privacy = privacy or Privacy(self.store)
        # External clients/models are loaded once, only when RAG is enabled.
        from app.rag.generation import Generator, ScopeRail
        from app.rag.retrieval import Search

        self.search = search or Search(settings)
        self.generator = generator or Generator(settings)
        self.rail = rail or ScopeRail(self.generator)
        self.rail_lock = Lock()
        self.markdown_dir = settings.rag_data_dir / "markdown"
        self.markdown_dir.mkdir(mode=0o700, exist_ok=True)

    def register_identity(self, p: Principal, identity: IdentityInput) -> dict:
        token = self.store.put_identity(
            p,
            f"curated:{identity.identifier_type.upper()}:{identity.identifier}",
            identity.canonical_name,
            [*identity.aliases, identity.identifier],
            sorted(set([p.user_id, *identity.allowed_users])),
            curated=True,
        )
        return {"token": token}

    def ingest(self, p, data, readers, confidentiality, label=None, choices=None):
        if len(data) > self.settings.max_pdf_bytes:
            raise HTTPException(413, "PDF exceeds upload limit")
        pages = extract_pdf(data, self.settings)
        doc_id = uuid4().hex
        readers = sorted(set([p.user_id, *readers]))
        self.store.create_document(
            p,
            doc_id,
            readers,
            "other",
            confidentiality,
            max(page for page, _ in pages),
            document_language(pages),
        )
        path = self.markdown_dir / f"{doc_id}.md"
        try:
            safe_pages = [
                (page, self.privacy.pseudonymize(text, p, doc_id, choices))
                for page, text in pages
            ]
            markdown = "\n\n".join(text for _, text in safe_pages)
            classification = label or classify(markdown)
            with self.store.db() as db:
                db.execute(
                    "UPDATE documents SET classification=? WHERE id=?",
                    (classification, doc_id),
                )
            # Only the sanitized version is ever persisted outside the identity vault.
            path.write_text(markdown, encoding="utf-8")
            path.chmod(0o600)
            # The multilingual MPNet model has a shorter context than English MPNet.
            # Respect its actual limit instead of silently truncating indexed evidence.
            limit = min(260, self.search.encoder.max_seq_length - 16)
            if limit < 32:
                raise ValueError("Embedding model context is too small")
            chunks = chunk_pages(
                safe_pages,
                self.search.encoder.tokenizer,
                size=limit,
                overlap=min(40, limit // 5),
            )
            page_languages = {
                page: detect_language(text, default="und") for page, text in pages
            }
            self.search.index_chunks(
                [
                    {
                        **chunk,
                        "id": f"{doc_id}:{n}",
                        "tenant_id": p.tenant_id,
                        "document_id": doc_id,
                        "allowed_users": readers,
                        "classification": classification,
                        "confidentiality": confidentiality,
                        "title": f"Document {doc_id[:8]}",
                        "language": page_languages[chunk["page"]],
                    }
                    for n, chunk in enumerate(chunks)
                ]
            )
            self.store.status(doc_id, "ready")
        except Exception:
            # Ready-document filtering prevents partial-index exposure.
            self.store.status(doc_id, "failed")
            path.unlink(missing_ok=True)
            raise
        return {**self.store.document(p, doc_id), "chunks": len(chunks)}

    def delete(self, p: Principal, doc_id: str):
        doc = self.store.document(p, doc_id)
        if doc["owner"] != p.user_id:
            raise HTTPException(403, "Only the document owner may delete it")
        self.store.status(doc_id, "deleted")
        self.search.delete(p.tenant_id, doc_id)
        (self.markdown_dir / f"{doc_id}.md").unlink(missing_ok=True)
        with self.store.db() as db:
            db.execute("DELETE FROM mentions WHERE document_id=?", (doc_id,))
            # Erase uncurated identities that have no remaining document references.
            for row in db.execute(
                "SELECT token,payload FROM identities WHERE tenant=?", (p.tenant_id,)
            ).fetchall():
                payload = json.loads(self.store.cipher.decrypt(row["payload"]))
                if (
                    not payload.get("curated")
                    and not db.execute(
                        "SELECT 1 FROM mentions WHERE token=?", (row["token"],)
                    ).fetchone()
                ):
                    db.execute("DELETE FROM aliases WHERE token=?", (row["token"],))
                    db.execute("DELETE FROM identities WHERE token=?", (row["token"],))

    def ask(self, p: Principal, request: Question) -> dict:
        language = request.language or detect_language(
            request.question, default=self.settings.default_query_language
        )
        try:
            session = self.store.session(p, request.session_id)
        except HTTPException as exc:
            if exc.status_code == 423:
                raise HTTPException(423, message("session_locked", language)) from exc
            raise
        if request.restore_pii and "pii:read" not in p.scopes:
            raise HTTPException(403, "PII restoration requires pii:read")
        safe_question = self.privacy.pseudonymize(
            request.question,
            p,
            choices=request.identity_choices,
            language=language,
        )
        # NeMo runtime context is serialized; atomic session increments live in SQLite.
        with self.rail_lock:
            allowed = self.rail.allows(safe_question)
        if not allowed:
            session = self.store.session(p, request.session_id, reject=True)
            return {
                **session,
                "status": "out_of_scope",
                "language": language,
                "answer": message("out_of_scope", language),
                "answer_html": "",
                "citations": [],
                "claims": [],
            }
        self.store.session(p, request.session_id)  # Recheck concurrent lock/expiry.
        docs = {d["id"]: d for d in self.store.visible_docs(p)}
        hits = self.search.retrieve(
            safe_question, p, list(docs), request.classifications, request.top_k
        )
        # Recheck authoritative permissions/status after retrieval, before generation.
        docs = {d["id"]: d for d in self.store.visible_docs(p)}
        hits = [
            h
            for h in hits
            if h["_source"]["document_id"] in docs
            and h["_source"]["tenant_id"] == p.tenant_id
            and p.user_id in h["_source"]["allowed_users"]
        ]
        passages = [
            {
                "source_id": f"S{n}",
                "text": self.privacy.pseudonymize(h["_source"]["text"], p),
            }
            for n, h in enumerate(hits, 1)
        ]
        sources = {s["source_id"]: s["text"] for s in passages}
        answer = (
            self.generator.answer(safe_question, passages, language=language)
            if passages
            else None
        )
        claims = []
        for claim in answer.claims if answer else []:
            quotes = {e.source_id: e.quote for e in claim.evidence}
            ids = list(quotes)
            if not ids or any(
                s not in sources
                or not quotes.get(s, "").strip()
                or quotes[s] not in sources[s]
                for s in ids
            ):
                continue
            # Defensive output PII pass before any optional authorized restoration.
            claims.append(
                {
                    "text": self.privacy.pseudonymize(claim.text, p),
                    "source_ids": ids,
                    "quotes": {s: quotes[s] for s in ids},
                }
            )
        used = {s for c in claims for s in c["source_ids"]}
        allowed_tokens = set(TOKEN_RE.findall(" ".join(sources[s] for s in used)))

        def display(value):
            return (
                self.store.restore(value, p, allowed_tokens)
                if request.restore_pii
                else value
            )

        citations = []
        for n, hit in enumerate(hits, 1):
            sid = f"S{n}"
            if sid not in used:
                continue
            src = hit["_source"]
            citations.append(
                {
                    "source_id": sid,
                    "document_id": src["document_id"],
                    "title": src["title"],
                    "page": src["page"],
                    "classification": src["classification"],
                    "url": f"/api/v1/documents/{src['document_id']}/markdown",
                    "excerpt": display(sources[sid]),
                    "language": src.get("language", "und"),
                }
            )
        rendered = []
        plain = []
        for claim in claims:
            claim["text"] = display(claim["text"])
            claim["quotes"] = {s: display(q) for s, q in claim["quotes"].items()}
            refs = " ".join(f"[{s}]" for s in claim["source_ids"])
            plain.append(f"{claim['text']} {refs}")
            excerpts = " ".join(
                f"<mark>{html.escape(q)}</mark> [{s}]"
                for s, q in claim["quotes"].items()
            )
            rendered.append(f"<p>{html.escape(claim['text'])} {refs}<br>{excerpts}</p>")
        return {
            **session,
            "status": "answered" if claims else "insufficient_evidence",
            "language": language,
            "answer": "\n\n".join(plain) or message("insufficient_evidence", language),
            "answer_html": "".join(rendered),
            "claims": claims,
            "citations": citations,
        }

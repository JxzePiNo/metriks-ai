from typing import Literal

from pydantic import BaseModel, Field

from app.rag.language import DocumentLanguage, Language

Classification = Literal["financial", "technical", "mixed", "other"]
Confidentiality = Literal["internal", "confidential", "restricted"]


class Principal(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    scopes: set[str] = Field(default_factory=set)


class IdentityInput(BaseModel):
    # Explicit assertion by an authorized identity curator; never infer name merges.
    identifier: str = Field(min_length=3, max_length=256)
    identifier_type: Literal["email", "employee_id"]
    canonical_name: str = Field(min_length=1, max_length=256)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    allowed_users: list[str] = Field(default_factory=list, max_length=100)


class Question(BaseModel):
    session_id: str
    question: str = Field(min_length=1, max_length=4000)
    # Optional hint for short/ambiguous queries such as "API?". Otherwise auto-detect.
    language: Language | None = None
    classifications: list[Classification] = Field(default_factory=list)
    # Alias -> selected opaque token returned by a previous clarification response.
    identity_choices: dict[str, str] = Field(default_factory=dict)
    restore_pii: bool = False
    top_k: int = Field(default=5, ge=1, le=10)


class Claim(BaseModel):
    text: str = Field(max_length=4000)
    source_ids: list[str] = Field(max_length=10)
    # Verbatim excerpts, validated by the application against each cited passage.
    quotes: dict[str, str] = Field(default_factory=dict)


class Evidence(BaseModel):
    source_id: str
    quote: str = Field(max_length=4000)


class GeneratedClaim(BaseModel):
    text: str = Field(max_length=4000)
    # A list avoids dynamic object keys, unsupported by strict OpenAI schemas.
    evidence: list[Evidence] = Field(max_length=10)


class GeneratedAnswer(BaseModel):
    claims: list[GeneratedClaim] = Field(max_length=20)


class DocumentRecord(BaseModel):
    id: str
    tenant: str
    owner: str
    readers: list[str]
    title: str
    classification: Classification
    confidentiality: Confidentiality
    status: str
    pages: int
    language: DocumentLanguage = "und"


class UploadedDocument(DocumentRecord):
    chunks: int


class DocumentList(BaseModel):
    documents: list[DocumentRecord]


class IdentityResult(BaseModel):
    token: str


class SessionResult(BaseModel):
    session_id: str
    attempts: int
    attempts_remaining: int
    locked: bool = False


class Citation(BaseModel):
    source_id: str
    document_id: str
    title: str
    page: int
    classification: Classification
    url: str
    excerpt: str
    language: DocumentLanguage = "und"


class ChatResult(SessionResult):
    language: Language
    status: Literal["answered", "insufficient_evidence", "out_of_scope"]
    answer: str
    answer_html: str
    claims: list[Claim]
    citations: list[Citation]

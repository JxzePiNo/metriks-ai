import json
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.rag.models import (
    ChatResult,
    Classification,
    Confidentiality,
    DocumentList,
    DocumentRecord,
    IdentityInput,
    IdentityResult,
    Principal,
    Question,
    SessionResult,
    UploadedDocument,
)

router = APIRouter(prefix="/api/v1", tags=["rag"])
bearer = HTTPBearer(auto_error=False)


def principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    settings = request.app.state.settings
    if not settings.rag_enabled:
        raise HTTPException(
            503, "RAG is disabled; set RAG_ENABLED=true after configuration"
        )
    if credentials is None:
        raise HTTPException(401, "Bearer credentials required")
    try:
        tokens = json.loads(settings.rag_api_tokens.get_secret_value())
        for token, claims in tokens.items():
            if secrets.compare_digest(token, credentials.credentials):
                return Principal.model_validate(claims)
    except (ValueError, TypeError, AttributeError, ValidationError) as exc:
        raise HTTPException(503, "Invalid server authentication configuration") from exc
    raise HTTPException(401, "Invalid credentials")


User = Annotated[Principal, Depends(principal)]


def service(request: Request):
    with request.app.state.rag_init_lock:
        if request.app.state.rag_service is None:
            try:
                from app.rag.service import RAGService

                request.app.state.rag_service = RAGService(request.app.state.settings)
            except Exception as exc:
                raise HTTPException(
                    503, "RAG dependencies unavailable; check server configuration"
                ) from exc
    return request.app.state.rag_service


Service = Annotated[object, Depends(service)]


def require(p: Principal, scope: str):
    if scope not in p.scopes:
        raise HTTPException(403, f"Required scope: {scope}")


def invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as exc:
        # Do not log SDK exception bodies, original content, or identity values.
        raise HTTPException(
            503, "RAG operation failed; check dependencies and retry"
        ) from exc


@router.post("/identities", status_code=201, response_model=IdentityResult)
def register_identity(identity: IdentityInput, p: User, svc: Service):
    require(p, "identity:write")
    return invoke(svc.register_identity, p, identity)


@router.post("/documents", status_code=201, response_model=UploadedDocument)
def upload_document(
    p: User,
    svc: Service,
    file: Annotated[UploadFile, File()],
    allowed_users: Annotated[str, Form()] = "[]",
    confidentiality: Annotated[Confidentiality, Form()] = "confidential",
    classification: Annotated[Classification | None, Form()] = None,
    identity_choices: Annotated[str, Form()] = "{}",
):
    require(p, "documents:write")
    try:
        readers = json.loads(allowed_users)
        choices = json.loads(identity_choices)
        if (
            not isinstance(readers, list)
            or len(readers) > 100
            or any(not isinstance(u, str) or not 1 <= len(u) <= 128 for u in readers)
            or not isinstance(choices, dict)
            or len(choices) > 100
            or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in choices.items()
            )
        ):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            422,
            "allowed_users must be a JSON string array; identity_choices a string map",
        ) from exc
    # Ignore original filename: it can itself contain personal information.
    data = file.file.read(svc.settings.max_pdf_bytes + 1)
    return invoke(
        svc.ingest, p, data, readers, confidentiality, classification, choices
    )


@router.get("/documents", response_model=DocumentList)
def list_documents(p: User, svc: Service):
    require(p, "documents:read")
    return {"documents": svc.store.visible_docs(p)}


@router.get("/documents/{document_id}", response_model=DocumentRecord)
def get_document(document_id: str, p: User, svc: Service):
    require(p, "documents:read")
    return svc.store.document(p, document_id)


@router.get("/documents/{document_id}/markdown", response_class=FileResponse)
def get_markdown(document_id: str, p: User, svc: Service):
    require(p, "documents:read")
    doc = svc.store.document(p, document_id)
    return FileResponse(
        svc.markdown_dir / f"{doc['id']}.md",
        media_type="text/markdown",
        filename=f"{doc['id']}.md",
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, p: User, svc: Service):
    require(p, "documents:write")
    invoke(svc.delete, p, document_id)


@router.post("/sessions", status_code=201, response_model=SessionResult)
def create_session(p: User, svc: Service):
    require(p, "chat:write")
    return svc.store.new_session(p)


@router.get("/sessions/{session_id}", response_model=SessionResult)
def get_session(session_id: str, p: User, svc: Service):
    require(p, "chat:write")
    return svc.store.session(p, session_id)


@router.post("/chat", response_model=ChatResult)
def chat(question: Question, p: User, svc: Service):
    require(p, "chat:write")
    require(p, "documents:read")
    return invoke(svc.ask, p, question)

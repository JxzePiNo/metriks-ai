"""Local PyMuPDF extraction. Images are OCR'd locally, never sent to a provider."""

from fastapi import HTTPException


def extract_pdf(data: bytes, settings) -> list[tuple[int, str]]:
    import pymupdf

    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "A PDF file is required")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise HTTPException(422, "Invalid PDF") from exc
    with doc:
        if doc.needs_pass:
            raise HTTPException(422, "Encrypted PDFs must be unlocked before uploading")
        if len(doc) > settings.max_pdf_pages:
            raise HTTPException(413, "PDF exceeds page limit")
        pages = []
        for number, page in enumerate(doc, 1):
            text = page.get_text("text", sort=True)
            has_images = bool(page.get_images())
            if settings.ocr_enabled and (has_images or not text.strip()):
                try:
                    # Partial OCR preserves native text and recognizes image regions.
                    tp = page.get_textpage_ocr(
                        language=settings.ocr_language, dpi=200, full=not text.strip()
                    )
                    text = page.get_text("text", textpage=tp, sort=True)
                except (RuntimeError, ValueError) as exc:
                    raise HTTPException(
                        422, "OCR failed; install Tesseract and language data"
                    ) from exc
            elif has_images:
                raise HTTPException(
                    422, "This PDF contains images; enable OCR to ingest it"
                )
            tables = page.find_tables()
            for table in tables.tables:
                # Preserve native table structure before privacy processing.
                text += "\n\n" + table.to_markdown()
            if text.strip():
                pages.append((number, f"## Page {number}\n\n{text.strip()}"))
        if not pages:
            raise HTTPException(422, "No extractable text found")
        return pages


def classify(text: str) -> str:
    """Explainable POC classifier; runs locally on pseudonymized content."""
    import re

    words = set(re.findall(r"[^\W\d_]+", text.casefold()))
    financial = bool(
        words
        & {
            "revenue",
            "ebitda",
            "balance",
            "income",
            "financial",
            "profit",
            "cashflow",
            "assets",
            "liabilities",
            "budget",
            "ricavo",
            "ricavi",
            "fatturato",
            "bilancio",
            "bilanci",
            "reddito",
            "finanziario",
            "finanziaria",
            "finanziari",
            "finanziarie",
            "utile",
            "utili",
            "profitto",
            "profitti",
            "cassa",
            "costi",
            "attività",
            "passività",
            "contabilità",
            "liquidità",
            "patrimonio",
        }
    )
    technical = bool(
        words
        & {
            "api",
            "architecture",
            "technical",
            "deployment",
            "database",
            "software",
            "infrastructure",
            "engineering",
            "architettura",
            "architetture",
            "tecnico",
            "tecnica",
            "tecnici",
            "tecniche",
            "distribuzione",
            "infrastruttura",
            "infrastrutture",
            "ingegneria",
            "sviluppo",
            "sicurezza",
            "configurazione",
        }
    )
    return (
        "mixed"
        if financial and technical
        else ("financial" if financial else "technical" if technical else "other")
    )


def chunk_pages(
    pages: list[tuple[int, str]], tokenizer, size: int = 260, overlap: int = 40
) -> list[dict]:
    """Use model tokens, keep pages separate, never cut a pseudonym in half."""
    import re

    chunks = []
    for page, text in pages:
        # Group full words, so opaque PII tokens remain intact through chunk boundaries.
        words = re.findall(r"\S+\s*", text)
        start = 0
        while start < len(words):
            end = start
            used = 0
            while end < len(words):
                count = len(tokenizer.encode(words[end], add_special_tokens=False))
                if end > start and used + count > size:
                    break
                used += count
                end += 1
            chunks.append({"page": page, "text": "".join(words[start:end]).strip()})
            if end == len(words):
                break
            next_start = end
            used = 0
            while next_start > start + 1 and used < overlap:
                next_start -= 1
                used += len(
                    tokenizer.encode(words[next_start], add_special_tokens=False)
                )
            start = next_start
    return chunks

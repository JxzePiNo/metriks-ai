# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS build
RUN pip install --no-cache-dir uv==0.13.1
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
ARG INSTALL_RAG=false
# Install locked, non-dev dependencies from uv.lock (fails if the lock is stale).
COPY pyproject.toml uv.lock README.md ./
RUN if [ "$INSTALL_RAG" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends g++ && \
      rm -rf /var/lib/apt/lists/* && \
      uv sync --frozen --no-dev --no-install-project --extra rag && \
      uv pip install --python /opt/venv/bin/python \
        https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl \
        https://github.com/explosion/spacy-models/releases/download/it_core_news_lg-3.8.0/it_core_news_lg-3.8.0-py3-none-any.whl; \
    else uv sync --frozen --no-dev --no-install-project; fi

FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-ita libgomp1 ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system app && useradd --system --gid app --no-create-home app && \
    mkdir -p /app/data && chown app:app /app/data
ENV HF_HOME=/app/data/models
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

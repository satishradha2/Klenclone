FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN addgroup --system klen && adduser --system --ingroup klen klen

COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN pip install --no-cache-dir ".[postgres]" \
    && mkdir -p /app/var \
    && chown -R klen:klen /app/var

USER klen
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "klen_clone.web:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
USER klen
CMD ["python", "-m", "pytest", "-q", "tests/integration"]

# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRADIO_SERVER_PORT=7860 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_ANALYTICS_ENABLED=False

WORKDIR /app

# System libraries: PyMuPDF needs libgl/libxcb at import time on some builds.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py policy_engine.py policies.json sample_policy_rule.json ./
COPY tests ./tests

# Runtime artefacts (ledger + certificates) live here; mount a volume to persist.
RUN mkdir -p /app/workspace/receipts /app/workspace/exports \
    && useradd --create-home --uid 10001 overlord \
    && chown -R overlord:overlord /app

USER overlord

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/', timeout=4).status == 200 else 1)"

CMD ["python", "app.py"]

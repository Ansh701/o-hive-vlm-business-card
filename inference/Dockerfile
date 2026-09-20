FROM pytorch/pytorch:2.14.0-cuda12.6-cudnn9-runtime@sha256:a77983eb7a3042ccf41a94da547a7f54a47fb70da15c36d67a8e8a329ebaa098

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/model-cache

WORKDIR /service
COPY inference/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY inference ./inference
RUN useradd --create-home --uid 10001 model \
    && mkdir -p /opt/model-cache \
    && chown -R model:model /service /opt/model-cache

USER model
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=4)" || exit 1

CMD ["python", "-m", "uvicorn", "inference.app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--no-server-header"]

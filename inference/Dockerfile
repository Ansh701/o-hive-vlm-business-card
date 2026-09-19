FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/model-cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.12 python3-pip ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /service
COPY inference/requirements.txt ./requirements.txt
RUN python3.12 -m pip install --break-system-packages -r requirements.txt \
    && python3.12 -m pip install --break-system-packages \
       torch==2.6.0 --index-url https://download.pytorch.org/whl/cu126

COPY inference ./inference
RUN useradd --create-home --uid 10001 model \
    && mkdir -p /opt/model-cache \
    && chown -R model:model /service /opt/model-cache

USER model
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=3 \
    CMD curl --fail http://127.0.0.1:8001/health || exit 1

CMD ["python3.12", "-m", "uvicorn", "inference.app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--no-server-header"]


# CivicPulse AI worker: the API code plus the `ai` extra and the model weights.
#
#   docker build -f infra/ai-worker/Dockerfile -t civicpulse-ai-worker:dev apps/api
#
# The build context is apps/api, like the API image. Weights are baked in at
# build time rather than loaded into a volume by an init job:
# - the image is the whole deployable unit, so a given tag always runs the
#   weights its models.lock.json names, and rolling back the image rolls
#   back the model (embeddings are only comparable within one model id);
# - nothing at start-up depends on the Hugging Face Hub being reachable;
# - a volume would outlive a lock change and keep serving the old weights
#   unless the init job learned to notice and refetch.
# The cost is a larger image (about 600 MB of fp32 weights). The download
# layer depends only on the lock and the download script, so code changes
# don't refetch it.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    AI_PROVIDER=onnx \
    AI_MODEL_DIR=/models \
    AI_FACE_BLUR=true \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# Dependencies, including onnxruntime (CPU), tokenizers and
# opencv-python-headless. No torch, no CUDA. uv is mounted for this step
# rather than copied in: the worker never needs it at runtime, and it would
# add 40 MB to the image.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=from=ghcr.io/astral-sh/uv:0.13.9,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project --extra ai

# Weights, verified against the committed lock (the script exits non-zero
# on any hash mismatch).
COPY models.lock.json ./
COPY app/__init__.py ./app/__init__.py
COPY app/ai/__init__.py app/ai/models_lock.py ./app/ai/
COPY scripts/__init__.py scripts/download_models.py ./scripts/
RUN python scripts/download_models.py --model-dir /models \
    && rm -rf /root/.cache/huggingface

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN useradd --system --uid 10001 --no-create-home civicpulse
USER civicpulse

# One task at a time: each process holds both CLIP towers (~1 GB resident)
# and ONNX Runtime already uses up to four threads per inference. The file
# check refuses to start on damaged weights instead of failing every task.
CMD ["sh", "-c", "python scripts/download_models.py --verify-only && exec celery -A app.worker:celery_app worker -Q ai --loglevel=INFO --concurrency=1 --hostname=ai@%h"]

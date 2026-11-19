# SelfX server image — used for BOTH the `api` and `worker` services (SPEC §1, §2).
#   api:    uvicorn app.main:app --host 0.0.0.0 --port 8000   (default CMD)
#   worker: python -m app.worker                              (compose command override)

# ---- stage 1: build python dependencies into an isolated venv ----
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# ---- stage 2: runtime ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# External tool engines (SPEC §8 notes). ImageMagick deliberately NOT installed (SPEC §10).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ghostscript \
      fonts-dejavu-core \
      tesseract-ocr \
      tesseract-ocr-eng \
      tesseract-ocr-deu \
      tesseract-ocr-fra \
      tesseract-ocr-spa \
      qpdf \
      pandoc \
      exiftool \
      ffmpeg \
      libmagic1 \
 && rm -rf /var/lib/apt/lists/*

# Non-root user; /data is the volume mount point for uploads/outputs/tmp.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 1000 selfx \
 && mkdir -p /data/uploads /data/outputs /data/tmp /models/huggingface \
 && chown -R selfx:selfx /data /models

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY app /srv/app

USER selfx

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

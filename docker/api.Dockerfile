FROM node:22-bookworm-slim

ARG QMD_VERSION=2.5.3

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:/opt/qmd/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libsqlite3-dev \
        pkg-config \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        sqlite3 \
        universal-ctags \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global --prefix /opt/qmd "@tobilu/qmd@${QMD_VERSION}" \
    && qmd --version

WORKDIR /app

COPY requirements.txt /tmp/backend-requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/backend-requirements.txt

COPY app ./app

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

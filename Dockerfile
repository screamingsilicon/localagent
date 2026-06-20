FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    git \
    build-essential \
    python3-dev \
    pkg-config \
    jq \
    ripgrep \
    fd-find \
    file \
    patch \
    diffutils \
    unzip \
    xz-utils \
    nodejs \
    npm \
    sqlite3 \
    cmake \
    tree \
 && ln -s /usr/bin/fdfind /usr/local/bin/fd \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

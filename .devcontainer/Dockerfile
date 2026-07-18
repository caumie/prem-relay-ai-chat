FROM python:3.13

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_PROJECT_ENVIRONMENT=/usr/local

# CodexのLinux sandboxはファイル範囲を制限するためにbubblewrapを使う。
# apply_patchをdevcontainer内で動作させるためにイメージに含める。
RUN apt-get update
RUN apt-get install -y --no-install-recommends bubblewrap
RUN rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /workspace-bootstrap
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen

# TODO: Codex拡張が初回起動時にCODEX_HOMEを自動作成するようになったら削除する。
# /root/.codex が存在しないとapp-serverを起動できないため、イメージ内に用意する。
RUN mkdir -p /root/.codex

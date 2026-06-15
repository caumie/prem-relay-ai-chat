FROM python:3.13-slim

RUN useradd --no-create-home --uid 10001 appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_PROJECT_ENVIRONMENT=/usr/local
ENV UV_NO_CACHE=1

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY src ./src
# ./dataのbindはcomposeで行う

USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.app:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

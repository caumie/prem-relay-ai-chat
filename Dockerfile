FROM python:3.13

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

ENV UV_PROJECT_ENVIRONMENT /usr/local
RUN pip install uv

WORKDIR /app
COPY ./pyproject.toml* ./
COPY ./uv.lock* ./
RUN uv sync

# COPY . .

# EXPOSE 8000
# CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]

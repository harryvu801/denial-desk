FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system -e ".[dev,evals]"

EXPOSE 8000
CMD ["uvicorn", "denial_desk.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

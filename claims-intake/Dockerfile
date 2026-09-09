FROM python:3.12-slim

WORKDIR /app

# Copy src before sync so hatchling can build the project wheel at image build time.
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY data ./data

RUN python -m pip install --no-cache-dir uv==0.12.5 \
    && uv sync --frozen --no-dev

EXPOSE 8000

# Use the venv binary so startup does not re-resolve via `uv run`.
CMD [".venv/bin/uvicorn", "claims.api.routes:app", "--host", "0.0.0.0", "--port", "8000"]

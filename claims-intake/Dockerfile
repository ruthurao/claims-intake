FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.12.5 \
    && uv sync --frozen --no-dev

COPY src ./src
COPY data ./data

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "claims.api.routes:app", "--host", "0.0.0.0", "--port", "8000"]

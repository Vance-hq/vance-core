FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY shared/ shared/
COPY agents/_base/ agents/_base/
COPY agents/forge/ agents/forge/

RUN pip install --no-cache-dir -e .

# Playwright browsers installed by the playwright service via shared volume.
# PLAYWRIGHT_BROWSERS_PATH set at runtime from environment.
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

CMD ["python", "-m", "agents.forge.main"]

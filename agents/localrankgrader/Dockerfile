FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libglib2.0-0 \
    libcairo2 \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY shared/ shared/
COPY agents/_base/ agents/_base/
COPY agents/localrankgrader/ agents/localrankgrader/

RUN pip install --no-cache-dir -e .

# Playwright browsers installed by the playwright service via shared volume.
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

CMD ["python", "-m", "agents.localrankgrader.main"]

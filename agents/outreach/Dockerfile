FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY shared/ shared/
COPY agents/_base/ agents/_base/
COPY agents/outreach/ agents/outreach/

RUN pip install --no-cache-dir -e .

# Playwright browsers are pre-installed by the playwright service
# and shared via the playwright_browsers volume.
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

CMD ["python", "-m", "agents.outreach.main"]

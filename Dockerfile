# One image for every service; the command picks the role (api | collector | classifier | migrate).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Explicit copies only: no .env, databases or git history ever enter the image.
COPY app/ app/
COPY data/places.json data/places.json
COPY migrations/ migrations/
RUN useradd --system --uid 10001 dcm
USER dcm
ENTRYPOINT ["python", "-m", "app"]

FROM base AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ tests/
USER dcm
ENTRYPOINT ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

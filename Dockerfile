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
# The commit this image was built from (CI: --build-arg GIT_SHA=$(git rev-parse --short HEAD)); shown by /api/health
ARG GIT_SHA=dev
ENV APP_VERSION=$GIT_SHA
LABEL org.opencontainers.image.revision=$GIT_SHA org.opencontainers.image.source="https://github.com/zawadgenweb2/dhaka-crime-map"
USER dcm
ENTRYPOINT ["python", "-m", "app"]

FROM base AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ tests/
USER dcm
ENTRYPOINT ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

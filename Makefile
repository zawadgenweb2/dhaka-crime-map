# Build, test and deploy entry points (what a CI/CD pipeline calls). Everything runs in Docker; no local Python needed.
#   make build        image tagged with the commit (dhaka-crime-map:<sha> and :latest)
#   make test-unit    tests that need no database (any CI runner)
#   make test         full suite against the compose Postgres (needs .env with POSTGRES_PASSWORD)
#   make deploy       in-house server: build, migrate (forward-only), restart the app services, smoke test
#   make smoke        health of every service + the event-store checks
# On the in-house server set COMPOSE_FILES="-f compose.yaml -f compose.inhouse.yaml" (the default below).

GIT_SHA ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo dev)
COMPOSE_FILES ?= -f compose.yaml -f compose.inhouse.yaml
COMPOSE = GIT_SHA=$(GIT_SHA) docker compose $(COMPOSE_FILES)
IMAGE = dhaka-crime-map

.PHONY: build test-image test-unit test migrate up deploy smoke ps logs places

build:
	docker build --target base --build-arg GIT_SHA=$(GIT_SHA) -t $(IMAGE):$(GIT_SHA) -t $(IMAGE):latest .

test-image:
	docker build --target test --build-arg GIT_SHA=$(GIT_SHA) -t $(IMAGE)-test:$(GIT_SHA) .

test-unit: test-image
	docker run --rm --network none $(IMAGE)-test:$(GIT_SHA) tests/test_pure.py

test:
	$(COMPOSE) --profile test run --rm --build test

migrate:
	$(COMPOSE) run --rm --build migrate

up:
	$(COMPOSE) up -d --build

# Forward-only: migrations run before the new containers start; a failed migration stops the deploy.
deploy: migrate up smoke

smoke:
	@$(COMPOSE) ps
	$(COMPOSE) exec -T api python -c "import json,ssl,urllib.request as u;print(json.load(u.urlopen('https://127.0.0.1:8100/api/health',context=ssl._create_unverified_context(),timeout=5)))" \
	  || $(COMPOSE) exec -T api python -c "import json,urllib.request as u;print(json.load(u.urlopen('http://127.0.0.1:8100/api/health',timeout=5)))"
	$(COMPOSE) exec -T collector python -m app healthcheck collector
	$(COMPOSE) exec -T classifier python -m app healthcheck classifier
	$(COMPOSE) exec -T classifier python -m app events-verify --sample 0 | head -40

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail 100 collector classifier

# Rebuild data/places.json from the committed source snapshots (no network)
places:
	docker run --rm --network none --user "$$(id -u):$$(id -g)" -v "$(CURDIR)":/work -w /work --entrypoint python $(IMAGE):latest scripts/build_places.py

# Bangladesh Crime Map: architecture and operations

This guide describes the service boundaries, network entry points, data model and processing flow of the in-house deployment. It reflects the application inspected on 28 October 2026. The deployed configuration and runtime state should be checked again before a production release.

## 1. Entry points and architecture

The public entry point is a FastAPI service on port **8100**. It serves the public map and read API. A separate FastAPI application on port **8101** provides the authenticated admin console. The inspected Docker Compose deployment does not contain a separate shared API gateway or reverse proxy. A future gateway or ingress could be added, but is not assumed here.

```mermaid
flowchart LR
    Browser[Public browser] -->|HTTPS :8100| API[Public API container]
    Operator[Admin browser] -->|HTTPS :8101| ADMIN[Admin API container]
    Papers[Newspaper sites] -->|Sitemaps and articles| COL[Collector container]
    API --> DB[(PostgreSQL 17)]
    ADMIN --> DB
    COL -->|articles, jobs, runs| DB
    WORK[Classifier container] -->|claims and updates work| DB
    WORK -->|structured extraction and judging :8090| LLM[Gemma llama-server on host]
    WORK -->|text embeddings :8091| EMB[EmbeddingGemma llama-server on host]
    WORK -->|optional geocoding| OSM[Nominatim]
    MIG[Migrate: one-shot container] --> DB
```

On the inspected host, the public and admin ports bind to `192.168.1.200`; PostgreSQL is exposed on `127.0.0.1:55432` for the host-networked classifier. The two llama.cpp services listen on host loopback at ports `8090` and `8091`. Actual binding and reachability depend on the deployment configuration and network.

## 2. Services and responsibilities

| Component | Runtime | Responsibility |
| --- | --- | --- |
| `api` | Docker | Public static map, safe incident summaries, statistics and version endpoint. |
| `admin` | Docker | Login, status, coverage, review, collection requests, event corrections, preview and Swagger. |
| `collector` | Docker | Schedule and manual requests; discover, filter and fetch newspaper articles; create jobs. |
| `classifier` | Docker, host networking | Claim work, call models, validate and save incidents, match events and enrich locations. |
| `db` | PostgreSQL 17 container | Persistent data, queues, locks, sessions and operational state. |
| `migrate` | One-shot container | Apply numbered SQL migrations, then exit. |
| `dhaka-llm` | Host user-level systemd | llama.cpp with Gemma 4 E2B Q8 for incident extraction and match judging. |
| `dhaka-embed` | Host user-level systemd | llama.cpp with text-only EmbeddingGemma 2 Q8 for report similarity. |

The application containers use the same image with different commands. PostgreSQL persists data in a named Docker volume. Classifier host networking shares the host network namespace; it enables access to model services on `127.0.0.1`, but also changes the container's network isolation. See [Docker's host-network documentation](https://docs.docker.com/engine/network/drivers/host/).

## 3. Processing flow

1. **Schedule or request:** the collector normally runs at 08:00 and 20:00 in Asia/Dhaka. Admins can request collection or a historical backfill.
2. **Discover and fetch:** publisher-specific sitemaps, URL and title signals and full-text checks select candidate stories. Robots policies and rate limits are applied. A filter can miss relevant news.
3. **Enqueue:** articles are stored and qualifying articles receive a row in `jobs`. Fresh work has higher priority than backfills.
4. **Extract:** a classifier worker claims a job with a lease, records a model call, asks in-house Gemma for structured output and saves the analysis.
5. **Validate and publish:** Python checks the evidence quote and location against the article. In automatic mode, reports passing the checks can publish without human review. Invalid incident dates can fall back to the publication or fetch date.
6. **Group reports:** the event matcher narrows candidate events by district, compatible category, place and date; embeddings rank candidates; Gemma judges the strongest candidates using distinctive shared facts and source quotes.
7. **Serve:** the public API serves event representatives, summaries and counts; the browser watches the data revision and refreshes its data when it changes.

A date filter only queries data already collected. It does not itself collect the requested historical period. Coverage, publisher availability, model quality and filter logic affect completeness.

## 4. Queues and delivery guarantees

There is **no separate Redis, RabbitMQ or Kafka service** in the inspected deployment. PostgreSQL acts as the queue store and coordination layer:

- `jobs` holds classification work, state, priorities, attempts, owner, lease and generation.
- `match_queue` holds reports waiting for event matching.
- `run_requests` holds manual collection requests; `schedule_slots` tracks scheduled runs.
- `previews` holds admin article-preview work.

Workers use short claim transactions and `FOR UPDATE SKIP LOCKED` so concurrent workers do not claim the same available row. A lease allows recovery when a worker dies, while generation and version checks prevent stale workers from publishing older results. Saved analyses can be reused after some downstream failures.

A lease and retry mechanism does **not** guarantee that a model is called exactly once in every failure scenario. The useful goal is safe recovery and preventing stale results from replacing newer ones. The database stores and coordinates work; the Python processes perform it.

## 5. Data model and duplicate matching

| Table group | Purpose |
| --- | --- |
| `articles`, `jobs` | Article URLs, bodies and work to process them. |
| `llm_calls`, `analyses`, `incidents` | Classification-call records, saved JSON and extracted reports with validation and review fields. |
| `events`, `event_reports` | One event representative and the associated report memberships. |
| `match_queue`, `match_decisions`, `event_exclusions`, `report_vectors` | Pending matching work, decision audit, admin split constraints and cached embeddings. |
| `runs`, `run_requests`, `schedule_slots`, `coverage_days`, `coverage_urls` | Collection operations and coverage tracking. |
| `admin_users`, `admin_sessions`, `admin_login_failures`, `admin_audit` | Admin authentication and operational audit data. |
| `data_revision` | Version counter used by the public page to detect changes. |

One article may describe multiple incidents. Multiple articles can report the same event. The `event_reports` table links each reduced report to an event; the earliest-published current report is selected as the primary. The public API uses that primary report as its representative. It returns a primary source URL and an additional-report count; the admin event detail can show linked reports.

Embedding similarity is only a candidate-ranking signal, not the final merge decision. The judge compares reports in both orders and requires at least two distinctive, grounded shared facts on each pass. A matching failure or unresolved ambiguity keeps reports separate; a failed matching operation is retried. An admin can split or merge groups. Same location alone does not prove that two crimes are the same event, and model decisions still require evaluation for false merges and missed duplicates.

The current category configuration marks sexual violence as mapped. The code supports a totals-only visibility mode, but no category was configured that way in the deployment inspected on 28 October 2026.

## 6. APIs and access boundaries

Public examples:

- `GET /api/config` — categories, geography and public configuration.
- `GET /api/incidents` — filtered published summaries and source information.
- `GET /api/stats` — counts for the same filters.
- `GET /api/version` — visible data revision.
- `GET /api/health` — basic API/database health.

Admin examples require appropriate authorization:

- `GET /api/meta`, `/api/runs`, `/api/coverage` — operational state.
- `POST /api/scrape` — enqueue a collection request.
- `GET /api/review/queue` and `POST /api/review/incidents/{id}` — inspect and correct incidents.
- `GET /api/events/status`, `/api/events/decisions`, `/api/events/{id}` — inspect event matching.
- `POST /api/events/split`, `/api/events/merge` — record corrections.
- `POST /api/classify`, `GET /api/classify/{id}` — run and inspect a preview. A preview does not publish an incident, but does create a preview record and consumes model capacity.

Admin passwords are stored as Argon2id hashes. The server uses session cookies, CSRF checks for browser mutations, login throttling and an audit trail. Public users do not receive database credentials. Their access is restricted by the public API's implemented routes and queries.

**Observed limitation:** the inspected containers use the same `dcm` database account, and that account was a PostgreSQL superuser. Separate least-privilege database roles are a recommended production improvement; application-level authorization alone does not restrict a compromised service's database credentials. PostgreSQL explains superuser privileges in its [role-attribute documentation](https://www.postgresql.org/docs/17/role-attributes.html).

The in-house API endpoints used a self-signed TLS certificate when inspected. Public deployment requires an appropriate certificate and a deliberate ingress, access and exposure design. TLS protects transport when correctly configured; it does not decide application permissions. See the [OWASP TLS guidance](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html).

## 7. Operations and verification

Useful **read-only** checks on the in-house server:

```bash
cd ~/dhaka-crime-map

git status --short --branch
docker compose -f compose.yaml -f compose.inhouse.yaml ps
systemctl --user status dhaka-llm dhaka-embed --no-pager
systemctl --user list-timers --all --no-pager
```

The admin console provides run history, queues and coverage without sharing database credentials. When a new article does not appear, follow it through article status, job, saved analysis, validation, event membership and the public filters. A scheduled collection can be interrupted by a service restart; collector recovery can retry interrupted work, but operators should verify the resulting run.

On 28 October 2026, the full test suite passed **115 tests** against a temporary, isolated PostgreSQL container. PR #1 had no reported automated GitHub checks. A local test pass and healthy endpoints are evidence about a particular revision and time; they are not proof of complete data coverage, semantic matching accuracy or production readiness.

Before a public release, validate deployment-specific ingress and TLS, database permissions, monitoring and alerting, backup restoration, newspaper terms and representative false-merge and missed-duplicate cases.

## 8. Code map

- Service configuration: [`compose.yaml`](../compose.yaml), [`compose.inhouse.yaml`](../compose.inhouse.yaml), [`Dockerfile`](../Dockerfile).
- Public and admin APIs: [`app/public.py`](../app/public.py), [`app/api.py`](../app/api.py), [`app/auth.py`](../app/auth.py).
- Collection and scheduling: [`app/collector.py`](../app/collector.py), [`app/scraper.py`](../app/scraper.py), [`app/scheduler.py`](../app/scheduler.py), [`app/sources.py`](../app/sources.py).
- Model processing and events: [`app/worker.py`](../app/worker.py), [`app/store.py`](../app/store.py), [`app/events.py`](../app/events.py).
- Database and schema: [`app/db.py`](../app/db.py), [`migrations/`](../migrations/).
- Host model services: [`deploy/inhouse-llm/`](../deploy/inhouse-llm/).

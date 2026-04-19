# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

LINE Messaging bot (FastAPI) that records group chat (text, images, files, links) and uses Gemini to classify and summarize. Dashboard (Jinja2 + HTTP-auth/session) exposes messages, links, summaries, tags, knowledge (entities / decisions / action items), semantic search, PDF export, and SAR evidence archive. See `README.md` for the user-facing walkthrough (Thai).

**Phases completed**: Phase 1 (ingest + categories), Phase 2 (full-text search, tagging, PDF export), Phase 3+4 (semantic search, knowledge extraction), Phase 5 (SAR/Evidence Archive — maps chat evidence to Thai educational standards, auto-classified via Gemini, exportable as PDF booklets).

## Commands

Local dev (expects a running MySQL 8, Qdrant, and MinIO — easiest via the compose files):

```bash
pip install -r requirements.txt
python -m app.init_db                                       # create tables
mysql -u root -p getchatbot < migrations/001_init.sql       # seed + then apply 002..011 in order
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Docker:

```bash
docker compose up -d --build                # local: MySQL + app (ports 3306 / 8000)
docker compose -f docker-compose.prod.yml up -d --build    # prod: MinIO + Qdrant + app on :9920
```

VPS deploy script: `deploy/deploy.sh`. DB bootstrap: `deploy/bootstrap_db.sh`. Nginx sample: `deploy/nginx.savechatbot.conf`.

There is no test suite, linter, or formatter configured — don't invent commands for them.

## Architecture

FastAPI app assembled in [app/main.py](app/main.py): lifespan creates tables, ensures the MinIO bucket and Qdrant collection, seeds the default dashboard admin from `.env`, and starts APScheduler. Three mount points: `/webhook` (LINE), dashboard routes at `/`, and `/media` for local static files. `/file/<path>` streams from MinIO ([app/dashboard/routes.py](app/dashboard/routes.py)) — media is served through the app, never via presigned URLs.

**Ingest pipeline** — [app/webhook.py](app/webhook.py):
1. Verify LINE HMAC signature, persist raw event to `webhook_raw_events` (idempotency via `webhook_event_id`).
2. Resolve/create `Group`, `User`, `GroupMember`; extract `Message` + `Link` rows; download media via [services/media_storage.py](app/services/media_storage.py) (LINE content API → MinIO; LINE only keeps media ~14d, so pull eagerly).
3. Classify text with Gemini ([services/gemini_client.py](app/services/gemini_client.py)) — picks existing category or invents one with `is_auto=1`.
4. Respond 200 immediately, then run enrichment in `BackgroundTasks` ([services/enrichment.py](app/services/enrichment.py)): OCR images, extract docs / YouTube transcripts, embed into Qdrant, extract knowledge (entities, decisions, action items), **auto-classify against Thai educational standards** (Phase 5).
5. If the message is a `!command`, dispatch via [services/commands.py](app/services/commands.py) and reply in the group.

**LINE commands**: `!สรุปวันนี้` / `!สรุปเมื่อวาน` / `!สรุปสัปดาห์` (summaries), `!ถาม <q>` / `!ask` (RAG answer), `!มฐ` / `!standards` (list active standards), `!แท็ก <code> [note]` (attach previous message to a standard), `!help`.

**Scheduler** — [app/scheduler.py](app/scheduler.py) uses APScheduler with `TIMEZONE` (default `Asia/Bangkok`). Daily job at `DAILY_SUMMARY_AT`, weekly at `WEEKLY_SUMMARY_DOW` + `WEEKLY_SUMMARY_AT`. Both call [services/summarizer.py](app/services/summarizer.py) per group; output stored in `summaries` with `UniqueConstraint(group_id, period, period_start)`.

**Storage topology** — three stores, each with a specific role:
- **MySQL** (SQLAlchemy 2, `models.py`): the authoritative relational store. `Base.metadata.create_all` runs at startup only in development (`ENVIRONMENT != production`); schema evolution is tracked in `migrations/001_init.sql` → `011_enrich_status.sql` — apply them in order on a fresh DB. Don't rely on `create_all` to add columns to an existing DB.
- **MinIO** ([services/minio_client.py](app/services/minio_client.py)): all user media. `messages.media_path` is the object key. Local dev falls through to `./storage/media` via the `/media` static mount.
- **Qdrant** ([services/embeddings.py](app/services/embeddings.py)): `savechatbot_messages` collection, Gemini `text-embedding-004` (768-dim). Powers `/search` semantic search in the dashboard.

**Knowledge layer** (Phase 3+4) — [services/knowledge_extractor.py](app/services/knowledge_extractor.py) parses messages into `entities` / `entity_mentions` / `decisions` / `action_items`. [services/rag.py](app/services/rag.py) is the retrieval side (top-8 semantic hits as context).

**SAR / Evidence Archive** (Phase 5) — Maps chat messages to Thai Basic Education Standards (สพฐ., 9 pre-seeded: 3 main + 6 sub-indicators):
- `Standard` model: `code`, `title`, `parent_code`, `academic_year`, `is_active`.
- `MessageStandard` junction: `message_id`, `standard_id`, `confidence` (0.0–1.0), `source` (`auto`|`manual`), `note`.
- `classify_standards()` in [services/gemini_client.py](app/services/gemini_client.py): Gemini-based auto-classification run as enrichment step 6 (confidence ≥ 0.4, up to 3 matches per message).
- Dashboard routes at `/standards*`: list, add, toggle, detail view (300 messages), manual attach/detach, per-standard PDF export.
- `GET /sar/export.pdf` (admin): full SAR booklet PDF — cover, TOC, one section per active standard, evidence galleries with images embedded as base64 data URIs (avoids WeasyPrint HTTP fetching). Single-standard export skips cover/TOC.
- PDF helpers in [services/pdf_export.py](app/services/pdf_export.py): `sar_book_to_pdf()` for SAR booklets, `summary_to_pdf()` for summaries (both use Kanit Thai font).

**Config** — [app/config.py](app/config.py) (`pydantic-settings`, reads `.env`). All runtime knobs (DB, LINE tokens, Gemini key/model, MinIO, Qdrant, dashboard creds, summary schedule) live there. `get_settings()` is `lru_cache`'d.

**Auth** — [app/dashboard/auth.py](app/dashboard/auth.py) uses bcrypt (pinned for the 72-byte limit) plus signed session cookies (`DASHBOARD_SECRET_KEY`). `DashboardUser.role` is `admin` or `viewer`; `require_admin` gates user management, category edits, standard management, and SAR export.

## Conventions specific to this repo

- All datetimes in the DB are naive UTC; convert to `settings.TIMEZONE` at the display edge (see `_to_bkk` in `dashboard/routes.py`).
- Migrations are plain SQL files, numbered. When adding a schema change, create a new `migrations/NNN_*.sql` — do **not** edit existing ones.
- Gemini prompts live inline in `services/gemini_client.py`, `knowledge_extractor.py`, and `summarizer.py`. Keep them in Thai where the existing prompt is Thai — the dashboard and LINE replies target Thai users.
- Prod compose uses a Docker network (no host port for MinIO/Qdrant); the app references them by container name (`savechatbot-minio`, `savechatbot-qdrant`).
- App listens on container port 8000; prod publishes it on host `:9920`.
- Images embedded in SAR/PDF exports use base64 data URIs fetched from MinIO — never pass presigned URLs to WeasyPrint.
- Cross-cutting HTTP security lives in [app/security.py](app/security.py) (Origin/Referer CSRF guard) and [app/main.py](app/main.py) (SlowAPI rate limiter). `/webhook` is exempt from CSRF since it validates LINE's HMAC instead.
- Enrichment is async and runs blocking work via `asyncio.to_thread`. Each message tracks `enrich_status` (`pending` / `done` / `failed`) + `enrich_attempts`. Use `POST /enrichment/retry` (admin) or `services.enrichment.retry_failed()` to re-process stuck rows.
- Logging: [app/logging_setup.py](app/logging_setup.py) emits plain text in dev and JSON in production (`ENVIRONMENT=production`). Extra context attached via `log.info("...", extra={"group": gid})` is promoted into the JSON payload.

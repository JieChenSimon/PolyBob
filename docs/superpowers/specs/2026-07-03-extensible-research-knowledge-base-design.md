# Extensible Research Knowledge Base Design

## Context

PolyBob needs a local research knowledge base that can ingest StatementDog now and additional research websites later. The user states they have authorization to crawl StatementDog directly. The system still records that authorization as configuration and audit metadata so future operators can see why automated ingestion is enabled.

## Scope

Build a generic knowledge-source framework with a StatementDog adapter. The first version stores structured documents locally, supports fast full-text search, exposes API endpoints, and provides a dashboard page. It must not block interactive dashboard requests while crawling.

## Architecture

- `libs/knowledge/` owns provider-neutral contracts, parsing, storage, search, source adapters, and the background service.
- SQLite remains the local embedded database. The implementation uses normal tables plus FTS5 when available. If FTS5 is unavailable, search falls back to indexed `LIKE` queries.
- `StatementDogSource` discovers URLs from sitemap data and parses public HTML into normalized knowledge documents. The adapter is enabled only when `statementdog_crawl_authorized=true`.
- `KnowledgeIngestionService` runs on startup only when explicitly enabled. It refreshes sources every configured interval and records status, failures, and crawl counts.
- FastAPI exposes search, recent documents, source status, and one manual refresh endpoint.
- The dashboard adds a "Research" route with query search, source filters, status cards, and direct source links.

## Data Model

Each document is stored with:

- `source_id`: stable source name, e.g. `statementdog`
- `document_id`: stable provider document key
- `url`, `title`, `document_type`, `ticker`, `company_name`
- `published_at`, `updated_at`, `captured_at`
- `language`, `summary`, `content`, `tags`
- `content_hash`, `metadata_json`

Source runs are stored with:

- `source_id`, `status`, `started_at`, `finished_at`
- `discovered_count`, `fetched_count`, `inserted_count`, `updated_count`, `failed_count`
- `message`

## StatementDog Behavior

- Discovery starts with `sitemap.xml.gz`.
- The initial filter keeps URLs under `/analysis`, `/blog/archives`, and `/analysis/*/earnings_calls/*` if encountered from linked pages or later sitemap variants.
- Lookback filtering uses `lastmod`, JSON-LD `datePublished`, and parsed dates when available.
- HTML parsing extracts JSON-LD article metadata, title/meta description, ticker from URL or page metadata, visible body text, and classification.
- Request concurrency and interval are configurable.

## API

- `GET /api/knowledge/search?q=&source=&document_type=&ticker=&limit=`
- `GET /api/knowledge/recent?source=&limit=`
- `GET /api/knowledge/sources`
- `POST /api/knowledge/sources/{source_id}/refresh`

## Dashboard

The new route is `/research`.

First screen:

- source health cards
- search box
- category chips
- recent documents
- result rows with title, ticker, type, summary, captured time, and source link

## Error Handling

Network, HTTP, parser, database, and authorization-disabled states are reported separately. The UI must show whether missing data is caused by disabled authorization, provider failure, no documents, or query with no matches.

## Validation

- Python unit tests cover schema, FTS fallback behavior, parser, source authorization gate, service status, and API contracts.
- Dashboard tests cover payload parsing and static route contract.
- Full validation remains `conda run -n polybob python -m pytest -q` plus `npm run build` in `apps/dashboard`.

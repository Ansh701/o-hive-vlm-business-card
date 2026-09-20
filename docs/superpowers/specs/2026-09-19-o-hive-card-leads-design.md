# O-HIVE Business Card Leads — Design Specification

## Intent and success criteria

Build a defensible take-home application that turns batches of business-card images into editable leads and a safe Excel workbook. It must feel like a focused document-intelligence workspace, run the Qwen model on AWS, survive individual-card failures, retain no raw images after processing, and remain small enough for the candidate to explain.

Success means the React application and FastAPI API share one Render origin; PostgreSQL persists only batch and lead records; each card is independently validated and processed; Qwen output is parsed, schema-validated, normalized, and retried at most once; reviewers can edit, select, remove, and export leads; tests run without paid inference; and AWS deployment is cost-guarded and reproducible.

## Architecture

The browser first creates a batch, then sends one multipart card request per image with concurrency limited to two. Each request validates real image bytes, dimensions, decompression safety, per-file and batch limits, and a SHA-256 duplicate key. The API re-encodes the card without metadata, holds those bytes in memory only while calling the authenticated AWS inference endpoint, then persists only the structured result. Starlette's upload handle is explicitly closed before inference. Completion of each HTTP request is genuine card-level progress; a failed request does not invalidate successful cards.

The FastAPI process uses SQLAlchemy 2 async sessions and PostgreSQL in production. SQLite through `aiosqlite` is supported for deterministic local tests only. Alembic owns schema changes. A single multi-stage Dockerfile builds Vite and serves the generated assets from FastAPI.

AWS runs `Qwen/Qwen3-VL-2B-Instruct` at BF16 on one `m7i.xlarge` CPU instance. This is not 4-bit/8-bit quantization. A short-lived AWS benchmark measured 19.594 seconds to load, 25.617 seconds for one controlled card, and 5,214.8 MiB peak RSS, with all seven expected fields schema-valid. This replaces the initial Qwen2.5-VL-3B candidate because the current 2B model is smaller, Apache-2.0 licensed, officially supported by Transformers, and adequate for the constrained extraction task. Tiny free shapes cannot hold the runtime; the measured CPU shape is standard paid EC2 whose cost can be offset by account-specific credits. GPU was not required after the CPU result, and the account's G/VT quotas were zero. On-Demand is used for evaluator reliability; Spot remains an explicit interruption-prone option. The stack must be deleted after the review window.

## Components and boundaries

- `backend/app/uploads.py`: byte, format, dimension, and duplicate validation; no model or database code.
- `backend/app/inference.py`: AWS client, HMAC authentication, strict prompt, one repair attempt, and schema validation.
- `backend/app/normalization.py`: conservative email and phone cleanup without invented country/name data.
- `backend/app/services.py`: batch state transitions and transactional persistence.
- `backend/app/export.py`: exact seven-column workbook and formula-injection defense.
- `backend/app/api.py`: typed HTTP contracts and status mapping.
- `frontend/src/*`: local file validation/previews, real XMLHttpRequest upload progress, bounded processing, review editing, selection, export, and themes.
- `inference/*`: AWS-only Qwen runtime with matching HMAC validation and structured extraction contract.
- `infra/aws/*`: one-instance deployment, HMAC-validating Lambda URL proxy, security-group-only private model ingress, one narrowly scoped SSM interface endpoint for runtime secret retrieval, least-privilege roles, minimal storage/logging, no NAT gateway/load balancer/Elastic IP, and optional cost budget.

## Data model

`batches` has UUID id, enumerated status, total/processed/successful/failed counts, and timestamps. `leads` has UUID id and batch id, safe display filename, SHA-256 content hash, the seven nullable official fields, status, JSON warnings, optional error message, and timestamps. Raw images and full model prompts/responses are never stored in PostgreSQL.

## Error and state model

Meaningful surfaces implement empty, loading, success, and error states. Duplicate cards return 409. Invalid images return 422 with actionable detail. Rate/cost limits return 429. Model timeouts and 5xx responses receive one bounded retry; malformed structured output receives one repair request. Exhausted retries create a failed lead record so the rest of the batch remains usable. A batch ends as `COMPLETED`, `PARTIAL_SUCCESS`, or `FAILED` based on persisted card outcomes.

## Security and privacy

Production disables debug/OpenAPI UI, validates Host, keeps CORS same-origin except explicit local origins, and sends CSP, HSTS, frame, content-type, referrer, and permissions headers. Public mutation endpoints receive per-IP and global in-memory throttling appropriate to a single-instance demo plus a database-backed daily card cap. Uploads accept JPEG/PNG/WEBP only after Pillow verifies decoded content, reject large files/pixels and duplicate hashes, ignore user filenames for filesystem paths, explicitly close temporary multipart handles, and never write application-owned raw-image files. Model and application services authenticate requests with a short-lived HMAC signature; secrets remain server-side. JSON logs carry request/batch/lead IDs, durations, result categories, and truncated content hashes but not raw images, filenames, full contact data, credentials, or model bodies.

Excel cells beginning with `=`, `+`, `-`, or `@` receive a leading apostrophe. Response headers force an `.xlsx` attachment. API writes use Pydantic allowlists with rejected extra fields and length bounds.

## UI system

Light is the first-visit default and the explicit preference is stored locally. Warm paper, ink, and controlled lime/cobalt accents create an editorial document-workspace feel. Glass is restricted to the header, uploader, processing tray, and focused edit surface; result rows remain dense and readable. Mobile uses lead cards; wider screens use a controlled table. All controls have labels, visible focus, at least 44px touch targets where applicable, keyboard equivalents, `aria-live` progress, and reduced-motion fallbacks.

## Verification

Backend unit/integration tests cover image attacks, deduplication, output repair, timeouts/5xx, normalization, persistence, editing, export ordering/formula safety, limits, and health/readiness. Frontend tests cover the twelve specified workflows with mocked same-origin APIs. Synthetic images are generated from controlled fixtures. Quality gates are Ruff, mypy, pytest, ESLint, TypeScript, Vitest, Vite build, npm audit, Alembic from a clean database, container build when Docker is available, local runtime probes, real AWS inference, and deployed browser QA. Gates requiring unavailable credentials or tooling must be reported as blocked rather than inferred.

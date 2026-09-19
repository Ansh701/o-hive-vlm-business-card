# O-HIVE Business Card Leads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a secure, tested, deployable business-card-to-leads application with AWS-hosted Qwen inference and same-origin Render hosting.

**Architecture:** React sends cards individually to FastAPI with concurrency two, so upload and processing progress are genuine and failures are isolated. FastAPI validates bytes, temporarily stores each image, calls a signed AWS inference service, persists normalized leads in PostgreSQL, then exports selected rows with openpyxl.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, asyncpg, Alembic, httpx, Pillow, openpyxl, pytest; React 19, TypeScript, Vite, Vitest, Testing Library, Lucide; Docker; EC2 + Qwen3-VL-2B-Instruct.

**Spec:** `docs/superpowers/specs/2026-09-19-o-hive-card-leads-design.md`

## Global Constraints

- One Render Web Service serves React and FastAPI from one origin.
- One PostgreSQL database and one AWS model service; no queue, cache, microservice fleet, or permanent image store.
- Official export fields remain nullable and ordered exactly as specified.
- Light is the first-visit default; accessibility and reduced motion are required.
- No external operation may be claimed without observed evidence.

## Review Focus

- A valid extension with non-image bytes must fail before inference.
- A malicious or traversal-style original filename must never become a filesystem path.
- Duplicate bytes in one batch must return 409 without consuming the daily model allowance twice.
- A formula-leading corrected value must export as inert text.
- A model timeout after the bounded retry must preserve other leads and finish the batch as partial success.

---

### Task 1: Repository and typed backend foundation

**Files:** Create `pyproject.toml`, `backend/app/config.py`, `backend/app/db.py`, `backend/app/models.py`, `backend/app/schemas.py`, `alembic.ini`, `backend/alembic/*`, and `backend/tests/conftest.py`.

**Interfaces:** Produces `Settings`, `Batch`, `Lead`, `BatchStatus`, `LeadStatus`, `get_session()`, and public Pydantic schemas consumed by all backend tasks.

- [ ] Write model/config tests first, run `pytest backend/tests/test_models.py -q`, and observe import failures.
- [ ] Implement UUID models, bounded settings, async engine/session dependency, schemas with `extra='forbid'`, and the initial Alembic migration.
- [ ] Re-run the focused tests, then `pytest backend/tests/test_models.py -q`; expected pass.
- [ ] Commit foundation files.

### Task 2: Secure image intake and normalization

**Files:** Create `backend/app/uploads.py`, `backend/app/normalization.py`, and `backend/tests/test_uploads.py`, `backend/tests/test_normalization.py`.

**Interfaces:** Produces `validate_image(filename: str, content: bytes, settings: Settings) -> ValidatedImage`, `normalize_email`, and `normalize_phone`.

- [ ] Add failing table-driven tests for valid images, fake JPEG, unsupported extension, bytes/pixels limits, decompression-bomb handling, and conservative normalization.
- [ ] Run the focused tests and confirm behavior failures rather than fixture errors.
- [ ] Implement Pillow verification/reopen, UUID temp naming metadata, SHA-256, normalized re-encoding, and non-guessing normalizers.
- [ ] Run both test modules; expected pass, then commit.

### Task 3: Strict AWS inference client

**Files:** Create `backend/app/inference.py`, `backend/tests/test_inference.py`, `inference/app.py`, `inference/requirements.txt`, and `inference/Dockerfile`.

**Interfaces:** Produces `BusinessCardLead`, `InferenceClient.extract(image: bytes, media_type: str)`, shared canonical JSON/prompt contract, and `POST /v1/extract` with timestamped HMAC verification.

- [ ] Write failing tests for valid JSON, fenced JSON, missing fields, malformed output repair, retry boundary, timeout, 5xx, and HMAC mismatch.
- [ ] Run tests to observe missing client/runtime failures.
- [ ] Implement a fixed-endpoint httpx client, HMAC over timestamp plus body hash, strict prompt, Pydantic validation, and one retry/repair only; implement the AWS model service with lazy Qwen loading.
- [ ] Re-run focused tests; expected pass, then commit.

### Task 4: Batch APIs and failure isolation

**Files:** Create `backend/app/services.py`, `backend/app/api.py`, `backend/app/main.py`, `backend/app/rate_limit.py`, and `backend/tests/test_api.py`.

**Interfaces:** Produces the batch/card/list/edit/delete routes, `/health`, `/ready`, batch counter transitions, security headers, and explicit same-origin CORS.

- [ ] Write failing API tests for create, multiple cards, duplicates, partial failure, persistence, patch validation, delete, malformed/missing IDs, rate limit, health, and readiness.
- [ ] Run focused tests and observe missing-route failures.
- [ ] Implement one-card multipart processing with a `finally` deletion path, transactional counters, database daily cap, per-IP limiter, response models, error mapping, and production middleware.
- [ ] Run `pytest backend/tests/test_api.py -q`; expected pass, then commit.

### Task 5: Safe Excel export

**Files:** Create `backend/app/export.py`, `backend/tests/test_export.py`, and extend `backend/app/api.py`.

**Interfaces:** Produces `build_workbook(leads) -> BytesIO` and `GET /api/batches/{id}/export.xlsx?lead_ids=...`.

- [ ] Write failing tests for real XLSX, exact column order, corrected values, selected rows, styles, and formula-leading cells.
- [ ] Run focused tests and observe missing exporter failures.
- [ ] Implement openpyxl workbook creation with frozen/filter header, bounded widths, inert formula values, and sanitized dated filename.
- [ ] Re-run export and API tests; expected pass, then commit.

### Task 6: React workflow and design system

**Files:** Create `frontend/package.json`, Vite/TypeScript/ESLint configs, `frontend/src/*`, and `frontend/src/__tests__/*`.

**Interfaces:** Produces the upload, per-card progress, review/edit/select/remove, export, zero-result, partial-success, error, and light/dark UI against `/api/*`.

- [ ] Add failing Vitest/Testing Library tests for all twelve required frontend behaviors and run `npm test -- --run`.
- [ ] Implement typed API calls, `URL.createObjectURL` lifecycle, XHR progress, concurrency two, semantic accessible components, persisted light-default theme, and responsive editorial CSS.
- [ ] Run Vitest, ESLint, `tsc --noEmit`, and the Vite build; expected pass.
- [ ] Commit frontend files.

### Task 7: Synthetic evaluation fixtures

**Files:** Create `scripts/generate_synthetic_cards.py`, `evaluation/ground-truth.json`, generated `evaluation/cards/*`, and `scripts/evaluate_extraction.py`.

**Interfaces:** Produces nine permission-safe synthetic cards and a field-level evaluator that calls the configured app/AWS endpoint without storing responses containing unexpected PII.

- [ ] Add a failing generator/evaluator test for all named variants and literal expected fields.
- [ ] Implement deterministic Pillow generation and scoring.
- [ ] Run generator tests and inspect representative images; expected pass and readable artifacts.
- [ ] Commit scripts, ground truth, and generated cards.

### Task 8: Packaging and deployment automation

**Files:** Create root `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `render.yaml`, `.env.example`, `infra/aws/*`, and `.github/workflows/ci.yml`.

**Interfaces:** Produces one same-origin production image, local PostgreSQL compose, Render blueprint, EC2 CloudFormation/user-data with no NAT/LB/EIP, cost budget template, and repeatable commands.

- [ ] Add failing static assertions/probes for Docker stages, Render single service, health path, AWS instance/IMDSv2, disk size, and absent NAT gateway.
- [ ] Implement deployment artifacts with secret placeholders only and least-privilege/runtime hardening.
- [ ] Run static checks, build locally where tooling exists, and probe `/`, `/health`, `/ready`.
- [ ] Commit deployment artifacts.

### Task 9: Documentation, security audit, and final verification

**Files:** Create `README.md`, `docs/security-review.md`, and update measurements/evaluation only from observed results.

**Interfaces:** Produces the full submission guide, exact `## AI Usage`, honest blocked-gate reporting, and the evaluator demo sequence.

- [ ] Run the complete backend/frontend/static/migration/secret-scan suites and record only fresh evidence.
- [ ] Review every requirement against code, write the README and security review, and mark credential/tooling-dependent gates as not run when applicable.
- [ ] Perform responsive browser QA when a browser can run the local build; repair findings with failing tests first.
- [ ] Run final full gates, inspect Git status/diff, commit, create/push the public repository only when authenticated, and verify local `main == origin/main` without force pushing.


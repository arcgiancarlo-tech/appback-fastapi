# FastAPI + Postgres Admin API

## What is included

The backend now exposes CRUD and reporting endpoints for:
- users
- templates
- managed files and uploads
- generations
- credit pack purchases
- RevenueCat refund and chargeback webhooks
- admin user management and user state reporting
- admin template management
- admin reporting for jobs, template usage, credit stats, site usage summary, and RevenueCat reversal events
- dashboard-specific admin and user endpoints for the major app views
- secured transactional email stub hooks for password reset, invite, and notify flows

## Endpoints

### Public/basic endpoints
- [GET]  /users/
- [POST] /users/
- [GET]  /templates/                     -> active templates only
- [POST] /templates/
- [GET]  /files/
- [POST] /files/
- [GET]  /files/{file_id}
- [GET]  /files/{file_id}/download-url
- [GET]  /files/{file_id}/public-url
- [POST] /files/upload-sessions
- [PUT]  /storage/upload/{token}
- [GET]  /storage/download/{token}
- [POST] /uploads/
- [GET]  /generations/
- [POST] /generations/
- [GET]  /generations/{generation_id}
- [GET]  /generations/{generation_id}/result-url
- [GET]  /generations/{generation_id}/result-public-url
- [POST] /generations/{generation_id}/status
- [POST] /generations/{generation_id}/result
- [GET]  /credit_packs/
- [POST] /credit_packs/
- [POST] /webhooks/revenuecat

### Internal transactional email hooks
- [GET]  /internal/transactional-email/health
- [POST] /internal/transactional-email/reset
- [POST] /internal/transactional-email/invite
- [POST] /internal/transactional-email/notify

All transactional email endpoints require the `X-Transactional-Email-Secret` header to match `TRANSACTIONAL_EMAIL_SHARED_SECRET`.
These endpoints are intentionally stubbed by default, so they can be wired into frontend or admin flows without sending real email yet.

### Admin user endpoints
- [GET]    /admin/users/                 -> optional `is_active`, `email_query`, `skip`, `limit`
- [GET]    /admin/users/count            -> filtered user count
- [GET]    /admin/users/state-summary    -> active/inactive and usage rollup
- [GET]    /admin/users/{user_id}

### Admin template CRUD
- [GET]    /admin/templates/             -> includes inactive by default
- [GET]    /admin/templates/{template_id}
- [POST]   /admin/templates/
- [PUT]    /admin/templates/{template_id}
- [DELETE] /admin/templates/{template_id}

Delete is a soft delete. It marks `is_active=false`, so admin listings and reports can still see historical templates.

### Admin reports
- [GET] /admin/jobs/
- [GET] /admin/reports/jobs/users
- [GET] /admin/reports/jobs/status-breakdown
- [GET] /admin/reports/template-usage
- [GET] /admin/reports/credits
- [GET] /admin/reports/usage-summary
- [GET] /admin/reports/revenuecat/refunds

### Dashboard routes for major views
#### Admin dashboard
- [GET] /dashboard/admin/overview
- [GET] /dashboard/admin/users
- [GET] /dashboard/admin/templates
- [GET] /dashboard/admin/jobs
- [GET] /dashboard/admin/credits
- [GET] /dashboard/admin/template-usage
- [GET] /dashboard/admin/jobs/users
- [GET] /dashboard/admin/jobs/status-breakdown

#### User dashboard
- [GET] /dashboard/users/{user_id}/overview
- [GET] /dashboard/users/{user_id}/jobs
- [GET] /dashboard/users/{user_id}/credits
- [GET] /dashboard/users/{user_id}/templates
- [GET] /dashboard/users/{user_id}/job-summary

#### Admin user reports
- `GET /admin/users/count`
  - Returns `{ "count": <int> }`, with optional `is_active` and `email_query` filters.
- `GET /admin/users/state-summary`
  - Returns total, active, inactive, users with generations, and users with credit packs.

#### Managed storage, signed URLs, and ComfyUI result linkage
Uploads are stored under backend-managed private paths and recorded in the `files` table.

For small/simple clients, `POST /uploads/` still accepts base64 payloads.

For large files, use the new signed upload flow:
1. `POST /files/upload-sessions` to allocate a managed file record and receive a time-limited `PUT` URL.
2. `PUT /storage/upload/{token}` with the raw request body, no base64 wrapping.
3. Fetch `GET /files/{file_id}/download-url` or `GET /generations/{generation_id}/result-url` to receive a time-limited download URL.
4. Download through `GET /storage/download/{token}`.

This keeps the storage root private while still allowing S3-style pre-signed upload/download behavior for local disk deployments.

For browser-facing assets, the app also mounts the managed storage root through FastAPI `StaticFiles` at `/assets`, so stored uploads, generated outputs, and template previews can be served directly with stable public URLs.

Generations now support:
- `input_file_id` and `output_file_id`
- `comfyui_job_id`, `comfyui_server_id`, `workflow_key`, `result_kind`
- `error_code`, `error_message`
- `queued_at`, `started_at`, `failed_at`, `completed_at`

`POST /generations/{generation_id}/status` updates job state and ComfyUI linkage.

`POST /generations/{generation_id}/result` stores the final output into managed storage, creates a `generation_output` file record, links it to the job, and marks the generation completed.

Stored file rows now also keep `original_filename`, so downloads can preserve a user-friendly name.

#### Jobs list report
Returns generation jobs joined with user email and template name.

Filters:
- `user_id`
- `template_id`
- `status`
- `skip`
- `limit`

#### Per-user jobs report
Returns generation totals by user, including completed / failed / pending counts and last job timestamp.

Filter:
- `template_id`

#### Job status breakdown report
Returns generation counts grouped by job status.

Filter:
- `template_id`

#### Template usage report
Returns:
- total template counts
- active vs inactive counts
- total generations
- per-template generation counts
- completed / failed / pending-style counts
- last usage timestamp

#### Credit stats report
Returns:
- total issued credits from `credit_packs`
- refunded credits from RevenueCat refund events
- chargeback credits from RevenueCat chargeback events
- net issued credits after reversals
- total purchased packs and purchase amount
- refunded and chargeback amounts
- net purchase amount after reversals
- generation counts by status
- consumed credits from stored `generations.credits_used` values
- remaining credits estimate/balance
- per-user breakdown

If a generation has `credits_used=0`, the report falls back to:

`consumed_credits = generation_count * credits_per_generation`

The `credits_per_generation` query parameter defaults to `1` and is retained for backward compatibility.

#### Site usage summary report
Returns:
- total users
- active vs inactive users
- users with generations
- users with credit packs
- total jobs
- jobs grouped by status
- total credits spent
- total credits earned
- total refunded credits
- total chargeback credits
- net credits balance

#### RevenueCat refunds report
Returns:
- processed RevenueCat refund and chargeback events
- refund vs chargeback counts
- credits revoked totals
- reversed money totals
- optional `user_id` filtering

## RevenueCat webhook config

Endpoint:
- `POST /webhooks/revenuecat`

This implementation accepts and persists refund-like RevenueCat events only:
- `REFUND`
- `CHARGEBACK`
- `CANCELLATION` when `cancel_reason` indicates a refund or chargeback

Other event types return `ignored` and do not affect reports.

Environment variables:
- `REVENUECAT_WEBHOOK_SECRET` -> optional shared secret for the webhook endpoint
- `REVENUECAT_PRODUCT_CREDITS` -> optional JSON mapping of RevenueCat product ids to credits, example `{"pack_100": 100, "pack_50": 50}`

Authentication:
- `Authorization: Bearer <secret>`
- or `X-Webhook-Secret: <secret>`

User matching:
- `event.app_user_id` may be the internal numeric user id
- or the user's email

Credit reversal mapping order:
1. `event.credits_revoked`
2. `event.credits`
3. `event.credit_amount`
4. `REVENUECAT_PRODUCT_CREDITS[event.product_id]`

Processed events are idempotent by RevenueCat event id.

## Tests

Added targeted API tests in:
- `fastapi_app/tests/test_admin_reports.py`
- `fastapi_app/tests/test_admin_usage_stats.py`
- `fastapi_app/tests/test_admin_users.py`
- `fastapi_app/tests/test_revenuecat_webhooks.py`
- `fastapi_app/tests/test_dashboard_endpoints.py`
- `fastapi_app/tests/test_generation_file_flow.py`

They cover:
- admin user listing, detail, count, and state summary
- admin template CRUD and soft delete behavior
- job listing and reporting filters
- template usage aggregation
- credit issuance and consumption reporting
- site usage summary reporting
- RevenueCat refund and chargeback webhook auth, idempotency, classification, and report integration
- dashboard-specific admin route wiring for all major admin views
- user dashboard overview, jobs, credits, templates, and 404 behavior
- upload storage, file records, generation status updates, and ComfyUI result linkage

Run with:
- `pytest fastapi_app/tests/test_admin_reports.py fastapi_app/tests/test_admin_usage_stats.py fastapi_app/tests/test_admin_users.py fastapi_app/tests/test_revenuecat_webhooks.py fastapi_app/tests/test_dashboard_endpoints.py fastapi_app/tests/test_generation_file_flow.py`

## Transactional email config

Environment variables:
- `TRANSACTIONAL_EMAIL_SHARED_SECRET` -> required, protects the internal email endpoints
- `TRANSACTIONAL_EMAIL_PROVIDER` -> defaults to `stub`
- `TRANSACTIONAL_EMAIL_STUB_MODE` -> defaults to `true`
- `TRANSACTIONAL_EMAIL_PROVIDER_API_KEY` -> optional until a real provider is wired
- `TRANSACTIONAL_EMAIL_FROM_EMAIL` -> defaults to `noreply@example.com`
- `APP_BASE_URL` -> used to build password reset links
- `INVITE_BASE_URL` -> optional override for invite links

Current behavior:
- Reset, invite, and notify endpoints return `202 Accepted`
- They generate link previews and a request fingerprint
- They do not send real email while provider mode is `stub` or `TRANSACTIONAL_EMAIL_STUB_MODE=true`
- If a non-stub provider is declared without an API key, the response surfaces the missing credential instead of silently pretending everything is live

Limitations:
- No SMTP, Resend, Postmark, SES, or SendGrid delivery integration yet
- No template rendering engine yet, only structured stub responses and link generation
- No persistence or retry queue for outbound mail yet
- Security currently relies on a shared secret header, so this should stay on internal/backend-only routes

## Testing procedure

Example local setup:

```bash
export DATABASE_URL=sqlite:///$(pwd)/fastapi_app/dev.db
export TRANSACTIONAL_EMAIL_SHARED_SECRET=dev-shared-secret
export TRANSACTIONAL_EMAIL_PROVIDER=stub
export TRANSACTIONAL_EMAIL_STUB_MODE=true
export TRANSACTIONAL_EMAIL_FROM_EMAIL=noreply@example.com
export APP_BASE_URL=https://app.spinaistudio.test
export FILE_URL_SIGNING_SECRET=dev-file-secret
export STORAGE_ROOT=$(pwd)/fastapi_app/storage
uvicorn fastapi_app.main:app --reload
```

If `DATABASE_URL` is unset, the app now falls back to `sqlite:///fastapi_app/dev.db` for local development. During pytest runs without an explicit `DATABASE_URL`, it falls back to in-memory SQLite.

Example calls:

```bash
curl -s http://127.0.0.1:8000/internal/transactional-email/health \
  -H 'X-Transactional-Email-Secret: dev-shared-secret'

curl -s http://127.0.0.1:8000/internal/transactional-email/reset \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'X-Transactional-Email-Secret: dev-shared-secret' \
  -d '{"email":"user@example.com","reset_token":"reset-token-12345"}'

curl -s http://127.0.0.1:8000/internal/transactional-email/invite \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'X-Transactional-Email-Secret: dev-shared-secret' \
  -d '{"email":"invitee@example.com","invite_token":"invite-token-12345","invited_by_email":"admin@example.com"}'

curl -s http://127.0.0.1:8000/internal/transactional-email/notify \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'X-Transactional-Email-Secret: dev-shared-secret' \
  -d '{"email":"user@example.com","subject":"Generation complete","message_text":"Your export is ready.","notification_type":"generation_complete","action_url":"https://app.spinaistudio.test/jobs/42","action_label":"View job"}'
```

Large file flow example:

```bash
SESSION_JSON=$(curl -s http://127.0.0.1:8000/files/upload-sessions \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{"owner_user_id":1,"filename":"result.mp4","mime_type":"video/mp4","kind":"user_input","max_bytes":500000000}')

UPLOAD_URL=$(python - <<'PY'
import json, os
print(json.loads(os.environ['SESSION_JSON'])['upload']['url'])
PY
)

curl -X PUT "$UPLOAD_URL" \
  -H 'Content-Type: video/mp4' \
  --data-binary @./result.mp4
```

Automated tests:
- `pytest fastapi_app/tests/test_transactional_email.py`
- `pytest fastapi_app/tests/test_generation_file_flow.py`

## Monitoring, logging, and security additions

The backend now includes a basic observability and protection layer for production-style deployments:

- Structured JSON request logging with per-request `X-Request-ID`
- Request timing via `X-Process-Time-Ms`
- Centralized logging for handled HTTP errors and unhandled exceptions
- Security headers on all responses:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
  - `Cache-Control: no-store`
- In-memory IP-based rate limiting with route grouping and `Retry-After`
- Health and readiness endpoints:
  - `GET /healthz`
  - `GET /readyz`
- Prometheus-style metrics endpoint:
  - `GET /metrics`

### Environment variables

- `LOG_LEVEL` → logging verbosity, defaults to `INFO`
- `RATE_LIMIT_REQUESTS` → allowed requests per window, defaults to `120`
- `RATE_LIMIT_WINDOW_SECONDS` → rate-limit window, defaults to `60`
- `ALLOWED_ORIGINS` → comma-separated CORS origins, defaults to `*`
- `STORAGE_ROOT` → managed file root, defaults to `/app/uploads` in container deployments
- `PUBLIC_ASSET_PATH` → FastAPI `StaticFiles` mount for public asset reads, defaults to `/assets`
- `FILE_URL_SIGNING_SECRET` → HMAC secret for upload/download signed URLs, set this in production
- `FILE_URL_TTL_SECONDS` → default signed URL lifetime, defaults to `900`
- `FILE_URL_MAX_TTL_SECONDS` → max allowed signed URL lifetime, defaults to `86400`
- `MAX_UPLOAD_BYTES` → hard cap for signed raw uploads, defaults to `1073741824` (1 GiB)

### Operational notes

- Rate limiting is in-memory, so counters reset on restart and are per-process. For multi-instance production, move this to Redis or an API gateway.
- `/readyz` performs a lightweight database `SELECT 1` check.
- `/metrics` exposes request counts, average latency, error totals, rate-limit hits, and uptime.

## Setup notes

Database URL behavior:
- Production Postgres: set `DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME`
- Heroku-style URLs using `postgres://...` are normalized automatically to `postgresql://...`
- Local development fallback: if `DATABASE_URL` is unset, the app uses `sqlite:///fastapi_app/dev.db`
- Test fallback: if pytest is running and `DATABASE_URL` is unset, the app uses in-memory SQLite
- SQLite connections automatically enable `check_same_thread=False`
- Alembic migrations now read the same resolved `DATABASE_URL`, so migrations follow the active backend instead of the hardcoded default

Quick examples:

```bash
# Production / Docker / hosted Postgres
export DATABASE_URL=postgresql://postgres:password@db:5432/mydb

# Local file-backed SQLite
export DATABASE_URL=sqlite:///$(pwd)/fastapi_app/dev.db

# Let local dev use the default fallback
unset DATABASE_URL
```

### Docker Compose production notes

The Docker Compose files now persist managed uploads in a named volume mounted at `/app/uploads` and include a `cloudflared` sidecar for the API tunnel.

Required production env vars:
- `DATABASE_URL`
- `FILE_URL_SIGNING_SECRET`
- `CLOUDFLARE_TUNNEL_TOKEN`

Expected Cloudflare setup:
- the tunnel token must belong to the named tunnel serving `api.spinaistudio.com`
- that tunnel should route traffic to the compose `app` service on port `8000`

Open `/docs` to inspect and exercise the API in Swagger.

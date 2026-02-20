# Expense Tracker

Render-first expense tracking app for CSV bank/credit-card imports, categorization, analytics, and AI insights.

## Current Status
This repo now includes the backend MVP scaffold:
1. FastAPI service with import/transaction/analytics/insight endpoints.
2. Background worker (RQ) for CSV ingestion and categorization.
3. PostgreSQL/Redis local setup with Docker Compose.
4. Next.js frontend with statement upload and transaction review UI.
5. Render Blueprint (`render.yaml`) for cloud deployment.

## Local Run (Docker)
1. Start services:
   ```bash
   docker compose up --build
   ```
2. API base URL:
   - `http://localhost:8000`
3. Health check:
   - `GET http://localhost:8000/healthz`
4. Host Postgres connection (for `psql`/VS Code):
   - `postgresql://expense_tracker:expense_tracker@127.0.0.1:55432/expense_tracker`

## Frontend Run (Local)
1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```
2. Configure API URL:
   ```bash
   cp .env.example .env.local
   ```
3. Start frontend:
   ```bash
   npm run dev
   ```
4. Open:
   - `http://localhost:3000`

## Clerk Auth Setup
1. Frontend env (`frontend/.env.local`):
   ```bash
   NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<your_publishable_key>
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
   ```
2. Backend env (`backend/.env`):
   ```bash
   CLERK_ENABLED=true
   CLERK_REQUIRE_AUTH=true
   CLERK_JWKS_URL=<clerk_jwks_url>
   CLERK_ISSUER=<expected_issuer>
   CLERK_AUDIENCE=<optional_audience>
   ```
3. With Clerk enabled, API requests must include a valid Clerk bearer token.
4. Imports, transactions, duplicate reviews, and insight reports are user-scoped by `user_id`.

## API Endpoints (MVP)
1. `POST /api/imports` (multipart file upload with key `file`)
2. `GET /api/imports/{import_id}`
3. `GET /api/categories`
4. `POST /api/categories`
5. `GET /api/transactions`
6. `POST /api/transactions` (manual transaction entry)
7. `POST /api/transactions/recategorize` (re-apply rule-based categorization on demand)
8. `PATCH /api/transactions/{transaction_id}/category`
9. `GET /api/analytics/categories`
10. `GET /api/analytics/merchants`
11. `POST /api/insights/generate`
12. `GET /api/insights/{insight_id}`
13. `GET /api/classification-rules`
14. `POST /api/classification-rules`
15. `PATCH /api/classification-rules/{rule_id}`
16. `DELETE /api/classification-rules/{rule_id}`
17. `POST /api/classification-rules/config/save` (export DB rules to git-backed config file)
18. `POST /api/classification-rules/config/load` (load rules from config file into DB)
19. `GET /api/duplicate-reviews`
20. `PATCH /api/duplicate-reviews/{review_id}`
21. `POST /api/duplicate-reviews/{review_id}/resolve`
22. `POST /api/duplicate-reviews/bulk-resolve`

## Deploy to Render
1. Push this repo to GitHub.
2. In Render, create a new Blueprint and point it to the repo.
3. Render reads `render.yaml` and provisions:
   - `expense-tracker-api` (web)
   - `expense-tracker-worker` (worker)
   - `expense-tracker-db` (PostgreSQL)
   - `expense-tracker-kv` (Redis-compatible key value)
4. Set `OPENAI_API_KEY` in service env vars.

## Notes
1. Categorization uses configurable DB-backed rules (priority ordered) with confidence scoring.
2. Current insight generation is deterministic placeholder logic.
3. Uploaded CSV content is stored in PostgreSQL so web and worker services can run independently on Render.
4. Frontend includes CSV upload, import status polling, manual expense entry, transaction filters, uncategorized review, and manual recategorization.
5. Frontend includes an Insights panel to generate and visualize reports (summary, top categories/merchants, savings actions).
6. Frontend includes a Classification Rules section to create/edit/activate/deactivate/delete mapping rules without code changes.
7. Rules can be stored in git at `backend/config/classification_rules.json` and synced to/from DB from the Rules tab.
8. Duplicate imports are now queued in `duplicate_reviews` for user review instead of being silently dropped.
9. Duplicate queue actions: `Mark Duplicate` removes queue item, `Not Duplicate` creates the transaction and removes queue item.
10. Duplicate queue supports bulk actions on currently shown rows with safeguards (`confirm=true`, explicit IDs, count match, max batch size).
11. Next step is replacing placeholder insights with an LLM provider adapter.
12. Duplicate prevention key is currently: `transaction_date + merchant_name + amount + direction`.
13. Redis token-bucket rate limiting is enabled by default for `/api/*`.
14. Default policies:
    - `strict` (`POST /api/imports`, `POST /api/transactions/recategorize`, `POST /api/duplicate-reviews/bulk-resolve`): `12/min`
    - `write` (other non-GET API calls): `60/min`
    - `read` (`GET`/`HEAD` API calls): `240/min`
15. Clerk login is integrated in the frontend (`SignedIn`/`SignedOut` + token forwarding to backend).

## Rate Limiting Config
Set in backend env (see `backend/.env.example`):
1. `RATE_LIMIT_ENABLED`
2. `RATE_LIMIT_FAIL_OPEN`
3. `RATE_LIMIT_KEY_PREFIX`
4. `RATE_LIMIT_READ_PER_MINUTE`
5. `RATE_LIMIT_WRITE_PER_MINUTE`
6. `RATE_LIMIT_STRICT_PER_MINUTE`

## Import Troubleshooting
1. Check latest imports:
   ```sql
   SELECT id, status, queue_job_id, total_rows, processed_rows, error_message, updated_at
   FROM statement_imports
   ORDER BY created_at DESC
   LIMIT 10;
   ```
2. Re-run a stuck/failed import by uploading the same CSV again after fix deployment.
   - New failures now store the original exception in `error_message` (not only queue tail links).
3. Check worker logs:
   ```bash
   docker compose logs -f worker
   ```

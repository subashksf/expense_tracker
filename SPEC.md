# Expense Tracker App - Product and Technical Spec (v0.1)

## 1. Objective
Build an application that:
1. Accepts uploaded credit card and bank statement CSV files.
2. Parses and normalizes transactions across institutions.
3. Categorizes expenses into useful buckets (for example: merchandise shopping, groceries_indian, groceries_other, eating_out, subscriptions).
4. Uses an LLM to analyze spending and generate actionable cost-reduction recommendations.

## 2. Scope
### In Scope (MVP)
1. Single-user experience (expand to multi-user later).
2. CSV upload for statements from multiple institutions.
3. Automatic transaction categorization with manual override.
4. Monthly and custom-range spend summaries.
5. LLM-generated spend analysis and savings suggestions.
6. Category-level trends and top-merchant breakdown.

### Out of Scope (MVP)
1. Direct bank API integrations (Plaid, Yodlee, etc.).
2. Receipt OCR.
3. Shared household accounts and role management.
4. Native mobile app.

## 3. User Stories
1. As a user, I can upload statement CSV files and see all transactions in one place.
2. As a user, I can search/filter transactions and edit categories when auto-categorization is wrong.
3. As a user, I can see monthly spend by category and merchant.
4. As a user, I can request AI insights that tell me where I can reduce spend.
5. As a user, I can mark AI suggestions as useful/not useful so future suggestions improve.

## 4. Functional Requirements
1. CSV ingestion
   - Upload CSV files.
   - Detect schema per institution (column mapping).
   - Parse date, amount, currency, description, merchant (if available), debit/credit direction.
2. Data normalization
   - Normalize signs and transaction direction.
   - Normalize merchant names (for example: "AMZN Mktp US" -> "Amazon").
   - Deduplicate overlapping transactions across uploads.
   - Queue potential duplicates for user review instead of silently dropping them.
3. Categorization
   - Rule-based first pass (source category, merchant, and description/text rules).
   - Rules are configurable (stored in DB and editable via API/UI).
   - Rules can be exported/imported via git-backed JSON config.
   - ML/LLM fallback for uncertain transactions.
   - Confidence score per classification.
   - Manual recategorization by user.
4. Analytics
   - Category spend totals per month.
   - Merchant spend totals per month.
   - Spend trend over time.
5. LLM insights
   - Explain major spend drivers.
   - Flag unusually high recurring costs.
   - Suggest realistic cost reductions (for example: "reduce eating_out by 15%").
   - Include rationale tied to user transaction data.

## 5. Suggested Category Taxonomy (Initial)
1. groceries_indian
2. groceries_other
3. eating_out
4. merchandise_shopping
5. subscriptions
6. travel
7. transportation
8. utilities
9. rent_or_mortgage
10. insurance
11. healthcare
12. entertainment
13. education
14. transfers
15. uncategorized

## 6. High-Level Architecture
1. Frontend (Web App)
   - Upload statements.
   - Transaction list and edit UI.
   - Dashboards for spend and trends.
   - AI insights panel.
2. Backend API
   - Auth/session (Clerk JWT verification for `/api/*`).
   - File upload endpoint.
   - Transaction/category CRUD.
   - Analytics endpoints.
   - Insights generation endpoint.
3. Ingestion Worker
   - Async processing after upload.
   - CSV parsing, normalization, dedupe, categorization.
4. Database (PostgreSQL)
   - Stores users, files, transactions, categories, overrides, insights.
5. Queue/Cache (Redis)
   - Background jobs and task status.
6. Object Storage
   - Deferred for post-MVP optimization.
   - MVP stores uploaded CSV content in PostgreSQL.
7. LLM Provider Abstraction
   - Single service layer for model calls.
   - Prompts + structured JSON output schema.

## 7. Processing Pipeline
1. User uploads CSV.
2. Backend stores CSV content + creates `statement_import` record.
3. Background worker parses CSV using institution-specific mapping.
4. Transactions normalized into canonical schema.
5. Deduplication pass runs.
6. Categorization engine assigns category + confidence.
   - Active rules are evaluated by ascending `priority`.
7. Data persisted and import status marked complete.
8. User reviews and optionally edits categories.
9. Potential duplicate rows are added to duplicate review queue.
10. User requests insight report for date range.
11. LLM prompt built from aggregates + notable transactions.
12. Insight report persisted and displayed.

## 8. Data Model (Core Tables)
1. `users`
2. `accounts` (credit card/checking/savings)
3. `statement_imports`
4. `uploaded_files`
5. `transactions`
6. `categories`
7. `classification_rules`
8. `transaction_category_overrides`
9. `duplicate_reviews`
10. `insight_reports`
11. `insight_feedback`

## 9. Canonical Transaction Fields
1. `id`
2. `user_id`
3. `account_id`
4. `transaction_date`
5. `posted_date` (optional)
6. `amount`
7. `currency`
8. `direction` (debit/credit)
9. `description_raw`
10. `merchant_normalized`
11. `category_id`
12. `category_confidence`
13. `source_import_id`
14. `dedupe_fingerprint`
15. `created_at`

## 10. Categorization Strategy
1. Rule Engine (high precision)
   - Merchant exact matches.
   - Description keyword rules.
   - Source category contains rules.
   - Priority-ordered rule evaluation.
2. Heuristic Layer
   - Recurring pattern detection for subscriptions.
   - Amount/date periodicity clues.
3. LLM Layer (when confidence low)
   - Input: normalized merchant + description + amount context.
   - Output: category + confidence + short reason.
4. User Feedback Loop
   - Manual edits stored as overrides.
   - Overrides become learned rules over time.

## 11. LLM Insights Design
1. Input to model
   - Category totals, month-over-month changes, recurring charges, top merchants.
2. Output format (structured JSON)
   - `summary`
   - `top_spend_drivers`
   - `potential_savings_actions`
   - `risk_flags`
   - `confidence`
3. Prompt guardrails
   - Do not fabricate transactions.
   - Cite only provided aggregates/transactions.
   - Keep recommendations measurable and practical.
4. Cost controls
   - Run insights on demand, not every upload.
   - Use aggregate summaries to reduce token volume.

## 12. API Surface (MVP)
1. `POST /api/imports` - upload CSV
2. `GET /api/imports/:id` - import status
3. `GET /api/transactions` - list/filter transactions
4. `PATCH /api/transactions/:id/category` - manual category update
5. `GET /api/analytics/categories` - spend by category
6. `GET /api/analytics/merchants` - spend by merchant
7. `POST /api/insights/generate` - generate LLM insights
8. `GET /api/insights/:id` - fetch saved insight report
9. `GET /api/classification-rules` - list categorization rules
10. `POST /api/classification-rules` - create categorization rule
11. `PATCH /api/classification-rules/:id` - update categorization rule
12. `DELETE /api/classification-rules/:id` - delete categorization rule
13. `POST /api/classification-rules/config/save` - export rules to config file
14. `POST /api/classification-rules/config/load` - load rules from config file
15. `GET /api/duplicate-reviews` - list duplicate review queue
16. `PATCH /api/duplicate-reviews/:id` - update duplicate review status
17. `POST /api/duplicate-reviews/:id/resolve` - resolve queue item (`mark_duplicate` or `not_duplicate`)
18. `POST /api/duplicate-reviews/bulk-resolve` - bulk resolve shown queue items with safeguards

## 13. Non-Functional Requirements
1. Security
   - Encrypt data at rest and in transit.
   - Securely store LLM/API keys.
   - Validate Clerk JWTs against JWKS and enforce bearer auth when enabled.
2. Privacy
   - Minimize sending raw transaction rows to LLM when aggregates are enough.
   - Add data-retention controls for uploaded files.
3. Reliability
   - Idempotent imports.
   - Retryable background jobs.
4. Observability
   - Structured logs for imports and categorization decisions.
   - Metrics for ingestion success rate, categorization confidence, LLM cost.

## 14. Suggested Tech Stack
1. Frontend: Next.js + TypeScript
2. Backend API: FastAPI (Python)
3. Worker: Celery or RQ
4. DB: PostgreSQL
5. Queue/Cache: Redis
6. ORM: SQLAlchemy + Alembic
7. Charts: Recharts or ECharts
8. LLM: OpenAI API via a small provider adapter layer

## 15. Hosting and Deployment (Render First)
1. Initial cloud target: Render.
2. Render services for MVP:
   - Web Service: `api` (FastAPI)
   - Worker Service: `worker` (background ingestion + categorization jobs)
   - Managed PostgreSQL
   - Managed Key Value (Redis-compatible)
3. File storage:
   - MVP: store uploaded CSV content in PostgreSQL so API and worker can run independently.
   - Later: move raw files to object storage for better durability and lower DB bloat.
4. Environment strategy:
   - `dev`: local docker-compose
   - `prod`: Render-managed services
   - Auth provider: Clerk (frontend sign-in + backend JWT verification)
5. Future option:
   - Consider AWS migration later if scale/compliance/cost profile requires it.
   - Do not optimize for AWS in MVP implementation right now.

## 16. Delivery Plan
1. Phase 1 (Core ingestion + UI)
   - CSV upload, parse, normalize, transaction list.
2. Phase 2 (Categorization)
   - Rule engine + manual overrides.
3. Phase 3 (Analytics dashboards)
   - Category and merchant trends.
4. Phase 4 (LLM insights)
   - Insight generation endpoint + UI.
5. Phase 5 (Hardening)
   - Security, observability, test coverage, performance tuning.

## 17. Open Questions
1. Which bank/credit-card CSV formats should be supported first?
2. Should income tracking be included in MVP or expense-only?
3. Is multi-currency support required now?
4. Do you want monthly budgets and alerting in MVP?

# Backlog

1. Mitigate false positives in duplicate detection:
   Legitimate repeated transactions can be marked as duplicates when they share `transaction_date`, `merchant_name`, `amount`, and `direction`.
2. Replace deterministic insight generation with an LLM provider adapter and structured output contract.
3. Add a local `users` profile cache in PostgreSQL keyed by Clerk `user_id` (Clerk remains source of truth for auth).
4. Sync local user cache via Clerk webhooks (`user.created`, `user.updated`, `user.deleted`) with idempotent upserts.
5. Use local user cache for admin reporting and SQL joins while avoiding credential storage in app DB.
6. [P0] Harden multi-tenant isolation by making `categories` and `classification_rules` user-scoped (or explicitly global + admin-only).
7. [P0] Add Clerk webhook signature verification and complete local user cache sync flow.
8. [P0] Add data protection controls: retention policy for uploaded CSVs, secure backups, and account/data deletion flow.
9. [P0] Add strict ingestion guards: CSV schema validation, file size limits, row limits, and clear import error reporting.
10. [P0] Add authorization tests to prove users cannot access or mutate other users' data.
11. [P0] Add production observability: structured logs, error tracking, queue/job metrics, and alerting.
12. [P1] Automate Postgres backups and test restore runbook.
13. [P1] Add abuse controls: upload quotas and stricter write/expensive-endpoint limits.
14. [P1] Add LLM guardrails: budget caps, timeout/retry limits, and per-user usage ceilings.
15. [P1] Add launch legal baseline: privacy policy, terms, and financial-data processing disclosure.

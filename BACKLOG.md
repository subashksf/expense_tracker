# Backlog

1. Mitigate false positives in duplicate detection:
   Legitimate repeated transactions can be marked as duplicates when they share `transaction_date`, `merchant_name`, `amount`, and `direction`.
2. Replace deterministic insight generation with an LLM provider adapter and structured output contract.
3. Add a local `users` profile cache in PostgreSQL keyed by Clerk `user_id` (Clerk remains source of truth for auth).
4. Sync local user cache via Clerk webhooks (`user.created`, `user.updated`, `user.deleted`) with idempotent upserts.
5. Use local user cache for admin reporting and SQL joins while avoiding credential storage in app DB.

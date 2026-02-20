export type ImportStatus = "queued" | "processing" | "completed" | "failed";

export type StatementImport = {
  id: string;
  filename: string;
  status: ImportStatus;
  queue_job_id?: string | null;
  total_rows: number;
  processed_rows: number;
  error_message: string | null;
  processing_started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type Transaction = {
  id: string;
  source_import_id: string;
  transaction_date: string | null;
  description_raw: string;
  merchant_normalized: string;
  amount: number;
  currency: string;
  direction: "debit" | "credit";
  category: string;
  category_confidence: number;
  created_at: string;
};

export type TransactionsQuery = {
  start_date?: string;
  end_date?: string;
  category?: string;
  limit?: number;
  offset?: number;
};

export type RecategorizeTransactionsInput = {
  start_date?: string;
  end_date?: string;
  category?: string;
  include_user_assigned?: boolean;
};

export type RecategorizeTransactionsResult = {
  scanned_rows: number;
  updated_rows: number;
  unchanged_rows: number;
  skipped_user_assigned_rows: number;
};

export type ManualTransactionInput = {
  transaction_date: string;
  description_raw: string;
  merchant_normalized?: string;
  amount: number;
  currency?: string;
  direction?: "debit" | "credit";
  category: string;
};

export type Category = {
  id: string;
  name: string;
  created_at: string;
};

export type ClassificationRuleType =
  | "source_category_contains"
  | "merchant_exact"
  | "merchant_contains"
  | "description_contains"
  | "text_contains";

export type ClassificationRule = {
  id: string;
  rule_type: ClassificationRuleType;
  pattern: string;
  category: string;
  confidence: number;
  priority: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ClassificationRuleCreateInput = {
  rule_type: ClassificationRuleType;
  pattern: string;
  category: string;
  confidence: number;
  priority: number;
  is_active: boolean;
};

export type ClassificationRuleUpdateInput = {
  rule_type?: ClassificationRuleType;
  pattern?: string;
  category?: string;
  confidence?: number;
  priority?: number;
  is_active?: boolean;
};

export type ClassificationRuleConfigSaveResult = {
  path: string;
  exported_rules: number;
};

export type ClassificationRuleConfigLoadResult = {
  path: string;
  loaded_rules: number;
  replaced_existing: boolean;
};

export type DuplicateReviewStatus = "pending" | "confirmed_duplicate" | "ignored";

export type DuplicateReview = {
  id: string;
  source_import_id: string;
  source_row_number: number;
  duplicate_scope: string;
  duplicate_reason: string;
  matched_transaction_id: string | null;
  transaction_date: string | null;
  description_raw: string;
  merchant_normalized: string;
  amount: number;
  currency: string;
  direction: "debit" | "credit";
  category: string;
  category_confidence: number;
  dedupe_fingerprint: string;
  status: DuplicateReviewStatus;
  review_note: string | null;
  created_at: string;
  reviewed_at: string | null;
};

export type DuplicateReviewResolveAction = "mark_duplicate" | "not_duplicate";

export type DuplicateReviewResolveResult = {
  action: string;
  status: string;
  deleted_review_id: string;
  created_transaction_id: string | null;
};

export type DuplicateReviewBulkResolveResult = {
  action: string;
  requested_count: number;
  processed_count: number;
  deleted_reviews_count: number;
  created_transactions_count: number;
  skipped_missing_count: number;
  skipped_non_pending_count: number;
};

export type InsightTopCategory = {
  category: string;
  amount: number;
};

export type InsightTopMerchant = {
  merchant: string;
  amount: number;
};

export type InsightSavingsAction = {
  category: string;
  current_spend: number;
  suggested_reduction_pct: number;
  suggested_monthly_savings: number;
  reason: string;
};

export type InsightPayload = {
  summary: string;
  top_spend_drivers: InsightTopCategory[];
  top_merchants: InsightTopMerchant[];
  potential_savings_actions: InsightSavingsAction[];
  risk_flags: string[];
  confidence: number;
};

export type InsightReport = {
  id: string;
  start_date: string | null;
  end_date: string | null;
  summary: string;
  payload: InsightPayload;
  created_at: string;
};

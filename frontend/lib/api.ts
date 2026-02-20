import type {
  Category,
  ClassificationRule,
  ClassificationRuleConfigLoadResult,
  ClassificationRuleConfigSaveResult,
  ClassificationRuleCreateInput,
  ClassificationRuleUpdateInput,
  DuplicateReviewBulkResolveResult,
  DuplicateReview,
  DuplicateReviewResolveAction,
  DuplicateReviewResolveResult,
  DuplicateReviewStatus,
  InsightReport,
  ManualTransactionInput,
  RecategorizeTransactionsInput,
  RecategorizeTransactionsResult,
  StatementImport,
  Transaction,
  TransactionsQuery
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
type AccessTokenProvider = () => Promise<string | null>;

let accessTokenProvider: AccessTokenProvider | null = null;

export function setApiAccessTokenProvider(provider: AccessTokenProvider | null): void {
  accessTokenProvider = provider;
}

async function authorizedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers ?? {});
  if (accessTokenProvider) {
    const token = await accessTokenProvider();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  return fetch(input, {
    ...init,
    headers
  });
}

function withQuery(path: string, params: TransactionsQuery): string {
  const query = new URLSearchParams();
  if (params.start_date) query.set("start_date", params.start_date);
  if (params.end_date) query.set("end_date", params.end_date);
  if (params.category) query.set("category", params.category);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const serialized = query.toString();
  return serialized ? `${path}?${serialized}` : path;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(errorBody || `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function uploadStatement(file: File): Promise<StatementImport> {
  const form = new FormData();
  form.append("file", file);
  const response = await authorizedFetch(`${API_BASE}/api/imports`, {
    method: "POST",
    body: form
  });
  return parseJsonResponse<StatementImport>(response);
}

export async function fetchImport(importId: string): Promise<StatementImport> {
  const response = await authorizedFetch(`${API_BASE}/api/imports/${importId}`);
  return parseJsonResponse<StatementImport>(response);
}

export async function fetchTransactions(params: TransactionsQuery): Promise<Transaction[]> {
  const url = withQuery(`${API_BASE}/api/transactions`, params);
  const response = await authorizedFetch(url);
  return parseJsonResponse<Transaction[]>(response);
}

export async function recategorizeTransactions(
  payload: RecategorizeTransactionsInput
): Promise<RecategorizeTransactionsResult> {
  const response = await authorizedFetch(`${API_BASE}/api/transactions/recategorize`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return parseJsonResponse<RecategorizeTransactionsResult>(response);
}

export async function updateTransactionCategory(
  transactionId: string,
  category: string
): Promise<Transaction> {
  const response = await authorizedFetch(`${API_BASE}/api/transactions/${transactionId}/category`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ category })
  });
  return parseJsonResponse<Transaction>(response);
}

export async function createManualTransaction(payload: ManualTransactionInput): Promise<Transaction> {
  const response = await authorizedFetch(`${API_BASE}/api/transactions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return parseJsonResponse<Transaction>(response);
}

export async function fetchCategories(): Promise<Category[]> {
  const response = await authorizedFetch(`${API_BASE}/api/categories`);
  return parseJsonResponse<Category[]>(response);
}

export async function createCategory(name: string): Promise<Category> {
  const response = await authorizedFetch(`${API_BASE}/api/categories`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ name })
  });
  return parseJsonResponse<Category>(response);
}

export async function fetchClassificationRules(): Promise<ClassificationRule[]> {
  const response = await authorizedFetch(`${API_BASE}/api/classification-rules`);
  return parseJsonResponse<ClassificationRule[]>(response);
}

export async function createClassificationRule(
  payload: ClassificationRuleCreateInput
): Promise<ClassificationRule> {
  const response = await authorizedFetch(`${API_BASE}/api/classification-rules`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return parseJsonResponse<ClassificationRule>(response);
}

export async function updateClassificationRule(
  ruleId: string,
  payload: ClassificationRuleUpdateInput
): Promise<ClassificationRule> {
  const response = await authorizedFetch(`${API_BASE}/api/classification-rules/${ruleId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return parseJsonResponse<ClassificationRule>(response);
}

export async function deleteClassificationRule(ruleId: string): Promise<void> {
  const response = await authorizedFetch(`${API_BASE}/api/classification-rules/${ruleId}`, {
    method: "DELETE"
  });
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(errorBody || `Request failed with status ${response.status}`);
  }
}

export async function saveClassificationRulesConfig(): Promise<ClassificationRuleConfigSaveResult> {
  const response = await authorizedFetch(`${API_BASE}/api/classification-rules/config/save`, {
    method: "POST"
  });
  return parseJsonResponse<ClassificationRuleConfigSaveResult>(response);
}

export async function loadClassificationRulesConfig(
  replaceExisting = true
): Promise<ClassificationRuleConfigLoadResult> {
  const response = await authorizedFetch(`${API_BASE}/api/classification-rules/config/load`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ replace_existing: replaceExisting })
  });
  return parseJsonResponse<ClassificationRuleConfigLoadResult>(response);
}

export async function fetchDuplicateReviews(params?: {
  import_id?: string;
  status?: DuplicateReviewStatus;
  limit?: number;
  offset?: number;
}): Promise<DuplicateReview[]> {
  const query = new URLSearchParams();
  if (params?.import_id) query.set("import_id", params.import_id);
  if (params?.status) query.set("status", params.status);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const url = `${API_BASE}/api/duplicate-reviews${query.toString() ? `?${query.toString()}` : ""}`;
  const response = await authorizedFetch(url);
  return parseJsonResponse<DuplicateReview[]>(response);
}

export async function updateDuplicateReview(
  reviewId: string,
  payload: { status: DuplicateReviewStatus; review_note?: string }
): Promise<DuplicateReview> {
  const response = await authorizedFetch(`${API_BASE}/api/duplicate-reviews/${reviewId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return parseJsonResponse<DuplicateReview>(response);
}

export async function resolveDuplicateReview(
  reviewId: string,
  action: DuplicateReviewResolveAction
): Promise<DuplicateReviewResolveResult> {
  const response = await authorizedFetch(`${API_BASE}/api/duplicate-reviews/${reviewId}/resolve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ action })
  });
  return parseJsonResponse<DuplicateReviewResolveResult>(response);
}

export async function resolveDuplicateReviewsBulk(
  reviewIds: string[],
  action: DuplicateReviewResolveAction
): Promise<DuplicateReviewBulkResolveResult> {
  const response = await authorizedFetch(`${API_BASE}/api/duplicate-reviews/bulk-resolve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      action,
      review_ids: reviewIds,
      expected_pending_count: reviewIds.length,
      confirm: true
    })
  });
  return parseJsonResponse<DuplicateReviewBulkResolveResult>(response);
}

export async function generateInsights(payload: {
  start_date?: string;
  end_date?: string;
}): Promise<InsightReport> {
  const response = await authorizedFetch(`${API_BASE}/api/insights/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  return parseJsonResponse<InsightReport>(response);
}

export async function fetchInsight(insightId: string): Promise<InsightReport> {
  const response = await authorizedFetch(`${API_BASE}/api/insights/${insightId}`);
  return parseJsonResponse<InsightReport>(response);
}

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class StatementImportResponse(BaseModel):
    id: str
    filename: str
    status: str
    queue_job_id: str | None
    total_rows: int
    processed_rows: int
    error_message: str | None
    processing_started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TransactionResponse(BaseModel):
    id: str
    source_import_id: str
    transaction_date: date | None
    description_raw: str
    merchant_normalized: str
    amount: float
    currency: str
    direction: str
    category: str
    category_confidence: float
    created_at: datetime


class CategoryUpdateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=64)


class RecategorizeTransactionsRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    category: str | None = Field(default=None, max_length=64)
    include_user_assigned: bool = False


class RecategorizeTransactionsResponse(BaseModel):
    scanned_rows: int
    updated_rows: int
    unchanged_rows: int
    skipped_user_assigned_rows: int


class ManualTransactionCreateRequest(BaseModel):
    transaction_date: date
    description_raw: str = Field(min_length=1, max_length=500)
    merchant_normalized: str | None = Field(default=None, max_length=255)
    amount: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    direction: Literal["debit", "credit"] = "debit"
    category: str = Field(min_length=1, max_length=64)


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class ClassificationRuleCreateRequest(BaseModel):
    rule_type: str = Field(min_length=1, max_length=64)
    pattern: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    confidence: float = Field(default=0.8, ge=0, le=1)
    priority: int = Field(default=100, ge=0, le=10000)
    is_active: bool = True


class ClassificationRuleUpdateRequest(BaseModel):
    rule_type: str | None = Field(default=None, min_length=1, max_length=64)
    pattern: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)
    priority: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None


class ClassificationRuleResponse(BaseModel):
    id: str
    rule_type: str
    pattern: str
    category: str
    confidence: float
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ClassificationRuleConfigSaveResponse(BaseModel):
    path: str
    exported_rules: int


class ClassificationRuleConfigLoadRequest(BaseModel):
    replace_existing: bool = True


class ClassificationRuleConfigLoadResponse(BaseModel):
    path: str
    loaded_rules: int
    replaced_existing: bool


class CategoryResponse(BaseModel):
    id: str
    name: str
    created_at: datetime


class CategorySpend(BaseModel):
    category: str
    total: float


class MerchantSpend(BaseModel):
    merchant: str
    total: float


class InsightGenerateRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


class InsightReportResponse(BaseModel):
    id: str
    start_date: date | None
    end_date: date | None
    summary: str
    payload: dict
    created_at: datetime


class DuplicateReviewResponse(BaseModel):
    id: str
    source_import_id: str
    source_row_number: int
    duplicate_scope: str
    duplicate_reason: str
    matched_transaction_id: str | None
    transaction_date: date | None
    description_raw: str
    merchant_normalized: str
    amount: float
    currency: str
    direction: str
    category: str
    category_confidence: float
    dedupe_fingerprint: str
    status: str
    review_note: str | None
    created_at: datetime
    reviewed_at: datetime | None


class DuplicateReviewUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    review_note: str | None = Field(default=None, max_length=1000)


class DuplicateReviewResolveRequest(BaseModel):
    action: Literal["mark_duplicate", "not_duplicate"]
    review_note: str | None = Field(default=None, max_length=1000)


class DuplicateReviewResolveResponse(BaseModel):
    action: str
    status: str
    deleted_review_id: str
    created_transaction_id: str | None = None


class DuplicateReviewBulkResolveRequest(BaseModel):
    action: Literal["mark_duplicate", "not_duplicate"]
    review_ids: list[str] = Field(min_length=1, max_length=500)
    expected_pending_count: int = Field(ge=1, le=500)
    confirm: bool = False


class DuplicateReviewBulkResolveResponse(BaseModel):
    action: str
    requested_count: int
    processed_count: int
    deleted_reviews_count: int
    created_transactions_count: int
    skipped_missing_count: int
    skipped_non_pending_count: int

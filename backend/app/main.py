import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import cors_origins, settings
from .db import Base, SessionLocal, engine, get_db
from .dedupe import build_dedupe_fingerprint
from .default_rule_seeds import DEFAULT_CLASSIFICATION_RULES
from .classification_engine import classify_with_rules, load_active_rules
from .insights import build_spend_insight
from .models import Category, ClassificationRule, InsightReport, StatementImport, Transaction, UploadedFile
from .queue import enqueue_import, read_job_state
from .schema import ensure_schema_compatibility
from .schemas import (
    CategoryCreateRequest,
    CategoryResponse,
    ClassificationRuleCreateRequest,
    ClassificationRuleResponse,
    ClassificationRuleUpdateRequest,
    CategorySpend,
    CategoryUpdateRequest,
    InsightGenerateRequest,
    InsightReportResponse,
    ManualTransactionCreateRequest,
    MerchantSpend,
    RecategorizeTransactionsRequest,
    RecategorizeTransactionsResponse,
    StatementImportResponse,
    TransactionResponse,
)

DEFAULT_CATEGORIES = [
    "groceries_indian",
    "groceries_other",
    "eating_out",
    "merchandise_shopping",
    "subscriptions",
    "travel",
    "transportation",
    "utilities",
    "rent_or_mortgage",
    "insurance",
    "healthcare",
    "entertainment",
    "education",
    "transfers",
    "uncategorized",
]

ALLOWED_RULE_TYPES = {
    "source_category_contains",
    "merchant_exact",
    "merchant_contains",
    "description_contains",
    "text_contains",
}


app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    with SessionLocal() as session:
        _seed_default_categories(session)
        _seed_default_classification_rules(session)


def _mark_failed(record: StatementImport, db: Session, reason: str) -> None:
    record.status = "failed"
    record.finished_at = datetime.now(UTC).replace(tzinfo=None)
    record.error_message = reason[:1000]
    db.commit()
    db.refresh(record)


def _normalize_category_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise ValueError("Category name must contain letters or numbers")
    return normalized[:64]


def _seed_default_categories(db: Session) -> None:
    existing = {row.name for row in db.query(Category).all()}
    missing = [name for name in DEFAULT_CATEGORIES if name not in existing]
    if not missing:
        return
    for name in missing:
        db.add(Category(name=name))
    db.commit()


def _seed_default_classification_rules(db: Session) -> None:
    existing_count = db.query(ClassificationRule.id).count()
    if existing_count > 0:
        return

    for item in DEFAULT_CLASSIFICATION_RULES:
        row = ClassificationRule(
            rule_type=item["rule_type"],
            pattern=item["pattern"],
            category=item["category"],
            confidence=float(item["confidence"]),
            priority=int(item["priority"]),
            is_active=1,
        )
        db.add(row)
    db.commit()


def _get_or_create_category(name: str, db: Session) -> str:
    normalized = _normalize_category_name(name)
    found = db.query(Category).filter(Category.name == normalized).one_or_none()
    if found is not None:
        return found.name
    db.add(Category(name=normalized))
    db.flush()
    return normalized


def _normalize_rule_type(value: str) -> str:
    rule_type = value.strip().lower()
    if rule_type not in ALLOWED_RULE_TYPES:
        raise ValueError(
            "Unsupported rule_type. Allowed values: "
            + ", ".join(sorted(ALLOWED_RULE_TYPES))
        )
    return rule_type


def _get_or_create_manual_import(db: Session) -> StatementImport:
    existing = db.query(StatementImport).filter(StatementImport.status == "manual").first()
    if existing is not None:
        return existing

    row = StatementImport(
        id=str(uuid.uuid4()),
        filename="manual_entries",
        status="manual",
        total_rows=0,
        processed_rows=0,
        finished_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(row)
    db.flush()
    return row


def _sync_import_status(record: StatementImport, db: Session) -> StatementImport:
    if record.status in {"completed", "failed"}:
        return record

    age = datetime.now(UTC).replace(tzinfo=None) - record.updated_at
    stale_threshold = timedelta(minutes=max(1, settings.import_stale_minutes))

    if not record.queue_job_id:
        if record.status == "processing" and age > stale_threshold:
            _mark_failed(
                record,
                db,
                (
                    "Import stalled in processing with no queue job id. "
                    "Run `docker compose logs worker` to inspect worker startup/job failures."
                ),
            )
        return record

    job_state = read_job_state(record.queue_job_id)
    if job_state is None:
        return record

    if job_state.status == "failed":
        reason = (
            f"Queue job failed ({record.queue_job_id}). "
            f"{job_state.error or 'Check worker logs with `docker compose logs worker`.'}"
        )
        _mark_failed(record, db, reason)
        return record

    if job_state.status == "missing" and age > stale_threshold:
        _mark_failed(
            record,
            db,
            (
                f"Queue job {record.queue_job_id} is missing and import became stale "
                f"after {settings.import_stale_minutes} minutes."
            ),
        )
        return record

    if record.status == "processing" and age > stale_threshold and job_state.status in {
        "queued",
        "started",
        "deferred",
        "scheduled",
    }:
        _mark_failed(
            record,
            db,
            (
                f"Import timed out in queue state '{job_state.status}' after "
                f"{settings.import_stale_minutes} minutes."
            ),
        )
        return record

    return record


def _to_import_response(record: StatementImport) -> StatementImportResponse:
    return StatementImportResponse(
        id=record.id,
        filename=record.filename,
        status=record.status,
        queue_job_id=record.queue_job_id,
        total_rows=record.total_rows,
        processed_rows=record.processed_rows,
        error_message=record.error_message,
        processing_started_at=record.processing_started_at,
        finished_at=record.finished_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_transaction_response(row: Transaction) -> TransactionResponse:
    return TransactionResponse(
        id=row.id,
        source_import_id=row.source_import_id,
        transaction_date=row.transaction_date,
        description_raw=row.description_raw,
        merchant_normalized=row.merchant_normalized,
        amount=row.amount,
        currency=row.currency,
        direction=row.direction,
        category=row.category,
        category_confidence=row.category_confidence,
        created_at=row.created_at,
    )


def _to_category_response(row: Category) -> CategoryResponse:
    return CategoryResponse(id=row.id, name=row.name, created_at=row.created_at)


def _to_rule_response(row: ClassificationRule) -> ClassificationRuleResponse:
    return ClassificationRuleResponse(
        id=row.id,
        rule_type=row.rule_type,
        pattern=row.pattern,
        category=row.category,
        confidence=float(row.confidence),
        priority=int(row.priority),
        is_active=bool(row.is_active),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@app.post(f"{settings.api_prefix}/imports", response_model=StatementImportResponse)
async def create_import(file: UploadFile = File(...), db: Session = Depends(get_db)) -> StatementImportResponse:
    import_id = str(uuid.uuid4())
    filename = file.filename or f"statement-{import_id}.csv"
    raw_content = await file.read()
    decoded_content = raw_content.decode("utf-8-sig", errors="ignore")

    record = StatementImport(id=import_id, filename=filename, status="queued")
    uploaded_file = UploadedFile(import_id=import_id, original_filename=filename, content_text=decoded_content)
    db.add(record)
    db.add(uploaded_file)
    db.commit()
    db.refresh(record)

    job_id = enqueue_import(import_id=record.id)
    if job_id:
        record.queue_job_id = job_id
        db.commit()
    db.refresh(record)

    return _to_import_response(record)


@app.get(f"{settings.api_prefix}/categories", response_model=list[CategoryResponse])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryResponse]:
    rows = db.query(Category).order_by(Category.name.asc()).all()
    return [_to_category_response(row) for row in rows]


@app.post(f"{settings.api_prefix}/categories", response_model=CategoryResponse)
def create_category(payload: CategoryCreateRequest, db: Session = Depends(get_db)) -> CategoryResponse:
    try:
        normalized = _normalize_category_name(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = db.query(Category).filter(Category.name == normalized).one_or_none()
    if existing is not None:
        return _to_category_response(existing)

    row = Category(name=normalized)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_category_response(row)


@app.get(f"{settings.api_prefix}/classification-rules", response_model=list[ClassificationRuleResponse])
def list_classification_rules(
    rule_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ClassificationRuleResponse]:
    query = db.query(ClassificationRule)
    if rule_type is not None:
        try:
            normalized = _normalize_rule_type(rule_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        query = query.filter(ClassificationRule.rule_type == normalized)
    if is_active is not None:
        query = query.filter(ClassificationRule.is_active == (1 if is_active else 0))

    rows = query.order_by(ClassificationRule.priority.asc(), ClassificationRule.created_at.asc()).all()
    return [_to_rule_response(row) for row in rows]


@app.post(f"{settings.api_prefix}/classification-rules", response_model=ClassificationRuleResponse)
def create_classification_rule(
    payload: ClassificationRuleCreateRequest, db: Session = Depends(get_db)
) -> ClassificationRuleResponse:
    try:
        normalized_rule_type = _normalize_rule_type(payload.rule_type)
        normalized_category = _get_or_create_category(payload.category, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = ClassificationRule(
        rule_type=normalized_rule_type,
        pattern=payload.pattern.strip().lower(),
        category=normalized_category,
        confidence=float(payload.confidence),
        priority=int(payload.priority),
        is_active=1 if payload.is_active else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_rule_response(row)


@app.patch(f"{settings.api_prefix}/classification-rules/{{rule_id}}", response_model=ClassificationRuleResponse)
def update_classification_rule(
    rule_id: str, payload: ClassificationRuleUpdateRequest, db: Session = Depends(get_db)
) -> ClassificationRuleResponse:
    row = db.get(ClassificationRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Classification rule not found")

    try:
        if payload.rule_type is not None:
            row.rule_type = _normalize_rule_type(payload.rule_type)
        if payload.pattern is not None:
            row.pattern = payload.pattern.strip().lower()
        if payload.category is not None:
            row.category = _get_or_create_category(payload.category, db)
        if payload.confidence is not None:
            row.confidence = float(payload.confidence)
        if payload.priority is not None:
            row.priority = int(payload.priority)
        if payload.is_active is not None:
            row.is_active = 1 if payload.is_active else 0
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(row)
    return _to_rule_response(row)


@app.delete(f"{settings.api_prefix}/classification-rules/{{rule_id}}")
def delete_classification_rule(rule_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    row = db.get(ClassificationRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Classification rule not found")

    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@app.get(f"{settings.api_prefix}/imports/{{import_id}}", response_model=StatementImportResponse)
def get_import(import_id: str, db: Session = Depends(get_db)) -> StatementImportResponse:
    record = db.get(StatementImport, import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Import not found")
    record = _sync_import_status(record, db)
    return _to_import_response(record)


@app.get(f"{settings.api_prefix}/transactions", response_model=list[TransactionResponse])
def list_transactions(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[TransactionResponse]:
    query = db.query(Transaction)
    if start_date is not None:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(Transaction.transaction_date <= end_date)
    if category:
        query = query.filter(Transaction.category == category)

    rows = (
        query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_transaction_response(row) for row in rows]


@app.post(
    f"{settings.api_prefix}/transactions/recategorize",
    response_model=RecategorizeTransactionsResponse,
)
def recategorize_transactions(
    payload: RecategorizeTransactionsRequest,
    db: Session = Depends(get_db),
) -> RecategorizeTransactionsResponse:
    rules = load_active_rules(db)
    if not rules:
        raise HTTPException(status_code=400, detail="No active classification rules found.")

    query = db.query(Transaction)
    if payload.start_date is not None:
        query = query.filter(Transaction.transaction_date >= payload.start_date)
    if payload.end_date is not None:
        query = query.filter(Transaction.transaction_date <= payload.end_date)
    if payload.category:
        query = query.filter(Transaction.category == payload.category)

    rows = query.all()
    scanned_rows = len(rows)
    updated_rows = 0
    unchanged_rows = 0
    skipped_user_assigned_rows = 0

    for row in rows:
        if not payload.include_user_assigned and float(row.category_confidence) >= 1.0:
            skipped_user_assigned_rows += 1
            continue

        new_category, new_confidence = classify_with_rules(
            rules=rules,
            description=row.description_raw,
            merchant=row.merchant_normalized,
            source_category="",
        )

        # If no rule matched (fallback uncategorized), do not downgrade already-categorized rows.
        if (
            row.category != "uncategorized"
            and new_category == "uncategorized"
            and abs(float(new_confidence) - 0.5) < 1e-9
        ):
            unchanged_rows += 1
            continue

        if row.category == new_category and abs(float(row.category_confidence) - float(new_confidence)) < 1e-9:
            unchanged_rows += 1
            continue

        row.category = new_category
        row.category_confidence = float(new_confidence)
        updated_rows += 1

    if updated_rows > 0:
        db.commit()

    return RecategorizeTransactionsResponse(
        scanned_rows=scanned_rows,
        updated_rows=updated_rows,
        unchanged_rows=unchanged_rows,
        skipped_user_assigned_rows=skipped_user_assigned_rows,
    )


@app.post(f"{settings.api_prefix}/transactions", response_model=TransactionResponse)
def create_manual_transaction(
    payload: ManualTransactionCreateRequest, db: Session = Depends(get_db)
) -> TransactionResponse:
    try:
        normalized_category = _get_or_create_category(payload.category, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    manual_import = _get_or_create_manual_import(db)

    merchant = (payload.merchant_normalized or "").strip()
    if not merchant:
        merchant = payload.description_raw.strip()[:100]

    dedupe_fingerprint = build_dedupe_fingerprint(
        transaction_date=payload.transaction_date,
        merchant_name=merchant,
        amount=payload.amount,
        direction=payload.direction,
    )
    existing = db.execute(
        select(Transaction.id).where(Transaction.dedupe_fingerprint == dedupe_fingerprint)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Duplicate transaction exists with same date, merchant, amount, and direction. "
                f"Existing transaction id: {existing}"
            ),
        )

    natural_key_existing = db.execute(
        select(Transaction.id).where(
            Transaction.transaction_date == payload.transaction_date,
            func.lower(Transaction.merchant_normalized) == merchant.lower(),
            func.round(Transaction.amount, 2) == round(payload.amount, 2),
            Transaction.direction == payload.direction,
        )
    ).scalar_one_or_none()
    if natural_key_existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Duplicate transaction exists with same date, merchant, amount, and direction. "
                f"Existing transaction id: {natural_key_existing}"
            ),
        )

    txn = Transaction(
        source_import_id=manual_import.id,
        transaction_date=payload.transaction_date,
        description_raw=payload.description_raw.strip(),
        merchant_normalized=merchant or "manual_entry",
        amount=payload.amount,
        currency=payload.currency.upper(),
        direction=payload.direction,
        category=normalized_category,
        category_confidence=1.0,
        dedupe_fingerprint=dedupe_fingerprint,
    )
    db.add(txn)

    manual_import.total_rows = (manual_import.total_rows or 0) + 1
    manual_import.processed_rows = (manual_import.processed_rows or 0) + 1
    manual_import.finished_at = datetime.now(UTC).replace(tzinfo=None)

    db.commit()
    db.refresh(txn)
    return _to_transaction_response(txn)


@app.patch(f"{settings.api_prefix}/transactions/{{transaction_id}}/category", response_model=TransactionResponse)
def update_transaction_category(
    transaction_id: str, payload: CategoryUpdateRequest, db: Session = Depends(get_db)
) -> TransactionResponse:
    txn = db.get(Transaction, transaction_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    try:
        normalized = _get_or_create_category(payload.category, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    txn.category = normalized
    txn.category_confidence = 1.0
    db.commit()
    db.refresh(txn)
    return _to_transaction_response(txn)


@app.get(f"{settings.api_prefix}/analytics/categories", response_model=list[CategorySpend])
def analytics_by_category(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CategorySpend]:
    query = db.query(Transaction.category, func.sum(Transaction.amount)).filter(Transaction.direction == "debit")
    if start_date is not None:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(Transaction.transaction_date <= end_date)
    rows = query.group_by(Transaction.category).all()
    return [CategorySpend(category=category or "uncategorized", total=float(total or 0.0)) for category, total in rows]


@app.get(f"{settings.api_prefix}/analytics/merchants", response_model=list[MerchantSpend])
def analytics_by_merchant(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[MerchantSpend]:
    query = db.query(Transaction.merchant_normalized, func.sum(Transaction.amount)).filter(
        Transaction.direction == "debit"
    )
    if start_date is not None:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(Transaction.transaction_date <= end_date)
    rows = query.group_by(Transaction.merchant_normalized).all()
    return [MerchantSpend(merchant=merchant or "unknown", total=float(total or 0.0)) for merchant, total in rows]


@app.post(f"{settings.api_prefix}/insights/generate", response_model=InsightReportResponse)
def generate_insights(payload: InsightGenerateRequest, db: Session = Depends(get_db)) -> InsightReportResponse:
    query = db.query(Transaction)
    if payload.start_date is not None:
        query = query.filter(Transaction.transaction_date >= payload.start_date)
    if payload.end_date is not None:
        query = query.filter(Transaction.transaction_date <= payload.end_date)

    transactions = query.all()
    if not transactions:
        raise HTTPException(status_code=400, detail="No transactions found for selected range")

    insight_payload = build_spend_insight(transactions)

    report = InsightReport(
        start_date=payload.start_date,
        end_date=payload.end_date,
        summary=insight_payload["summary"],
        payload_json=json.dumps(insight_payload),
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return InsightReportResponse(
        id=report.id,
        start_date=report.start_date,
        end_date=report.end_date,
        summary=report.summary,
        payload=insight_payload,
        created_at=report.created_at,
    )


@app.get(f"{settings.api_prefix}/insights/{{insight_id}}", response_model=InsightReportResponse)
def get_insight(insight_id: str, db: Session = Depends(get_db)) -> InsightReportResponse:
    report = db.get(InsightReport, insight_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Insight report not found")

    return InsightReportResponse(
        id=report.id,
        start_date=report.start_date,
        end_date=report.end_date,
        summary=report.summary,
        payload=json.loads(report.payload_json),
        created_at=report.created_at,
    )


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}

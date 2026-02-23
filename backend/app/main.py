import json
import hashlib
import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta
import math

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Numeric, cast, func, select, true
from sqlalchemy.orm import Session

from .auth import AuthContext, ClerkTokenVerifier, extract_bearer_token
from .config import cors_origins, settings
from .db import Base, SessionLocal, engine, get_db
from .dedupe import build_dedupe_fingerprint
from .default_rule_seeds import DEFAULT_CLASSIFICATION_RULES
from .classification_engine import classify_with_rules, load_active_rules
from .insights import build_spend_insight
from .models import (
    Category,
    ClassificationRule,
    DuplicateReview,
    InsightReport,
    StatementImport,
    Transaction,
    UploadedFile,
)
from .observability import configure_logging, init_sentry, monotonic_ms, utc_now_iso
from .queue import enqueue_import, read_job_state, read_queue_metrics
from .rate_limit import (
    RedisTokenBucketLimiter,
    pick_rate_limit_policy,
    resolve_rate_limit_identity,
)
from .rule_config import load_rules_config_file, resolve_rules_config_path, save_rules_config_file
from .schema import ensure_schema_compatibility
from .schemas import (
    CategoryCreateRequest,
    CategoryResponse,
    ClassificationRuleCreateRequest,
    ClassificationRuleConfigLoadRequest,
    ClassificationRuleConfigLoadResponse,
    ClassificationRuleConfigSaveResponse,
    ClassificationRuleResponse,
    ClassificationRuleUpdateRequest,
    CategorySpend,
    CategoryUpdateRequest,
    DuplicateReviewBulkResolveRequest,
    DuplicateReviewBulkResolveResponse,
    DuplicateReviewResponse,
    DuplicateReviewResolveRequest,
    DuplicateReviewResolveResponse,
    DuplicateReviewUpdateRequest,
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

ALLOWED_DUPLICATE_REVIEW_STATUS = {"pending", "confirmed_duplicate", "ignored"}
BULK_DUPLICATE_REVIEW_MAX = 500

configure_logging("expense_tracker.api")
init_sentry("expense_tracker.api")
logger = logging.getLogger("expense_tracker.api")
ADMIN_USER_IDS = {value.strip() for value in settings.admin_user_ids.split(",") if value.strip()}


app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
rate_limiter = RedisTokenBucketLimiter(settings.redis_url, key_prefix=settings.rate_limit_key_prefix)
token_verifier = ClerkTokenVerifier(settings) if settings.clerk_enabled else None


def _attach_cors_headers(request: Request, response: Response) -> Response:
    origin = request.headers.get("origin", "").strip()
    allowed = cors_origins()
    allow_all = "*" in allowed
    if allow_all:
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


def _json_api_error(request: Request, status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-Id"] = request_id
    return _attach_cors_headers(request, response)


def _get_request_id(request: Request) -> str:
    incoming = request.headers.get("x-request-id", "").strip()
    return incoming or str(uuid.uuid4())


def _get_auth_context(request: Request) -> AuthContext | None:
    if not settings.clerk_enabled:
        return None
    context = getattr(request.state, "auth_context", None)
    if context is not None:
        return context
    if settings.clerk_require_auth:
        raise HTTPException(status_code=401, detail="Authentication required")
    return None


def _get_request_user_id(request: Request) -> str | None:
    context = _get_auth_context(request)
    return context.user_id if context else None


def _require_admin(request: Request) -> str | None:
    user_id = _get_request_user_id(request)
    if not settings.clerk_enabled:
        return user_id
    if not ADMIN_USER_IDS:
        raise HTTPException(
            status_code=503,
            detail="No admin users configured. Set ADMIN_USER_IDS in backend environment.",
        )
    if user_id not in ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user_id


def _apply_user_scope(query, model, user_id: str | None):
    if not settings.clerk_enabled:
        return query
    if user_id is None:
        return query.filter(model.user_id.is_(None))
    return query.filter(model.user_id == user_id)


def _build_user_condition(model, user_id: str | None):
    if not settings.clerk_enabled:
        return true()
    if user_id is None:
        return model.user_id.is_(None)
    return model.user_id == user_id


def _apply_rate_limit_headers(
    response: Response,
    limit: int,
    remaining: float,
    policy_name: str,
    retry_after_seconds: int | None = None,
) -> None:
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, int(math.floor(remaining))))
    response.headers["X-RateLimit-Policy"] = policy_name
    if retry_after_seconds is not None:
        response.headers["Retry-After"] = str(max(1, retry_after_seconds))


@app.middleware("http")
async def observe_http_request(request: Request, call_next):
    request_id = _get_request_id(request)
    request.state.request_id = request_id
    started_ms = monotonic_ms()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001
        duration_ms = round(monotonic_ms() - started_ms, 2)
        logger.exception(
            "request_unhandled_exception",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
            },
        )
        raise

    duration_ms = round(monotonic_ms() - started_ms, 2)
    response.headers["X-Request-Id"] = request_id
    user_id = getattr(getattr(request.state, "auth_context", None), "user_id", None)
    logger.info(
        "request_complete",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "user_id": user_id,
        },
    )
    return response


@app.middleware("http")
async def enforce_authentication(request: Request, call_next):
    request.state.auth_context = None
    if not settings.clerk_enabled:
        return await call_next(request)
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if not request.url.path.startswith(settings.api_prefix):
        return await call_next(request)

    token = extract_bearer_token(request.headers.get("Authorization"))
    if not token:
        if settings.clerk_require_auth:
            return _json_api_error(request=request, status_code=401, detail="Missing bearer token")
        return await call_next(request)

    try:
        if token_verifier is None:
            return _json_api_error(request=request, status_code=503, detail="Clerk is not configured")
        request.state.auth_context = token_verifier.verify(token)
    except HTTPException as exc:
        return _json_api_error(request=request, status_code=exc.status_code, detail=str(exc.detail))

    return await call_next(request)


@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next):
    if not settings.rate_limit_enabled:
        return await call_next(request)
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if not request.url.path.startswith(settings.api_prefix):
        return await call_next(request)

    policy = pick_rate_limit_policy(request.method, request.url.path, settings)
    identity = resolve_rate_limit_identity(request)
    decision = rate_limiter.consume(policy=policy, identity=identity)

    if decision.error and not settings.rate_limit_fail_open:
        return _json_api_error(
            request=request,
            status_code=503,
            detail="Rate limiter unavailable. Try again shortly.",
        )

    if not decision.allowed:
        retry_after_seconds = int(max(1, math.ceil(decision.retry_after_ms / 1000.0)))
        response = JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "policy": policy.name,
                "retry_after_seconds": retry_after_seconds,
            },
        )
        _apply_rate_limit_headers(
            response=response,
            limit=policy.capacity,
            remaining=decision.remaining_tokens,
            policy_name=policy.name,
            retry_after_seconds=retry_after_seconds,
        )
        return _attach_cors_headers(request, response)

    response = await call_next(request)
    _apply_rate_limit_headers(
        response=response,
        limit=policy.capacity,
        remaining=decision.remaining_tokens,
        policy_name=policy.name,
    )
    if decision.error and settings.rate_limit_fail_open:
        response.headers["X-RateLimit-Bypass"] = "redis_unavailable"
    return response


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    with SessionLocal() as session:
        _seed_default_categories(session)
        _seed_default_classification_rules(session)
    logger.info(
        "api_startup_complete",
        extra={
            "app_env": settings.app_env,
            "rate_limit_enabled": settings.rate_limit_enabled,
            "clerk_enabled": settings.clerk_enabled,
            "admin_user_count": len(ADMIN_USER_IDS),
            "ops_metrics_enabled": settings.ops_metrics_enabled,
        },
    )


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

    try:
        configured_rules = load_rules_config_file()
    except Exception:  # noqa: BLE001
        configured_rules = []
    if not configured_rules:
        configured_rules = [dict(item, is_active=True) for item in DEFAULT_CLASSIFICATION_RULES]
        save_rules_config_file(configured_rules)

    for item in configured_rules:
        row = ClassificationRule(
            rule_type=item["rule_type"],
            pattern=item["pattern"],
            category=item["category"],
            confidence=float(item["confidence"]),
            priority=int(item["priority"]),
            is_active=1 if bool(item.get("is_active", True)) else 0,
        )
        db.add(row)
    db.commit()


def _resolve_category(name: str, db: Session, create_if_missing: bool = False) -> str:
    normalized = _normalize_category_name(name)
    found = db.query(Category).filter(Category.name == normalized).one_or_none()
    if found is not None:
        return found.name
    if create_if_missing:
        db.add(Category(name=normalized))
        db.flush()
        return normalized
    raise ValueError(f"Category '{normalized}' does not exist")


def _normalize_rule_type(value: str) -> str:
    rule_type = value.strip().lower()
    if rule_type not in ALLOWED_RULE_TYPES:
        raise ValueError(
            "Unsupported rule_type. Allowed values: "
            + ", ".join(sorted(ALLOWED_RULE_TYPES))
        )
    return rule_type


def _ensure_unique_dedupe_fingerprint(base_fingerprint: str, review_id: str, db: Session) -> str:
    candidate = base_fingerprint
    attempt = 0
    while db.execute(
        select(Transaction.id).where(Transaction.dedupe_fingerprint == candidate)
    ).scalar_one_or_none() is not None:
        raw = f"{base_fingerprint}|approved|{review_id}|{attempt}"
        candidate = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        attempt += 1
    return candidate


def _apply_duplicate_review_action(row: DuplicateReview, action: str, db: Session) -> str | None:
    if action == "mark_duplicate":
        db.delete(row)
        return None

    if action == "not_duplicate":
        dedupe_fingerprint = _ensure_unique_dedupe_fingerprint(
            base_fingerprint=row.dedupe_fingerprint,
            review_id=row.id,
            db=db,
        )

        txn = Transaction(
            user_id=row.user_id,
            source_import_id=row.source_import_id,
            transaction_date=row.transaction_date,
            description_raw=row.description_raw,
            merchant_normalized=row.merchant_normalized,
            amount=row.amount,
            currency=row.currency,
            direction=row.direction,
            category=row.category,
            category_confidence=float(row.category_confidence),
            dedupe_fingerprint=dedupe_fingerprint,
        )
        db.add(txn)

        source_import = db.get(StatementImport, row.source_import_id)
        if source_import is not None:
            source_import.processed_rows = (source_import.processed_rows or 0) + 1
            source_import.updated_at = datetime.now(UTC).replace(tzinfo=None)

        db.delete(row)
        db.flush()
        return txn.id

    raise ValueError("Unsupported action for duplicate review resolution")


def _get_or_create_manual_import(db: Session, user_id: str | None) -> StatementImport:
    query = db.query(StatementImport).filter(StatementImport.status == "manual")
    query = _apply_user_scope(query, StatementImport, user_id)
    existing = query.first()
    if existing is not None:
        return existing

    row = StatementImport(
        id=str(uuid.uuid4()),
        user_id=user_id if settings.clerk_enabled else None,
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


def _to_duplicate_review_response(row: DuplicateReview) -> DuplicateReviewResponse:
    return DuplicateReviewResponse(
        id=row.id,
        source_import_id=row.source_import_id,
        source_row_number=row.source_row_number,
        duplicate_scope=row.duplicate_scope,
        duplicate_reason=row.duplicate_reason,
        matched_transaction_id=row.matched_transaction_id,
        transaction_date=row.transaction_date,
        description_raw=row.description_raw,
        merchant_normalized=row.merchant_normalized,
        amount=row.amount,
        currency=row.currency,
        direction=row.direction,
        category=row.category,
        category_confidence=float(row.category_confidence),
        dedupe_fingerprint=row.dedupe_fingerprint,
        status=row.status,
        review_note=row.review_note,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _normalize_duplicate_review_status(value: str) -> str:
    status = value.strip().lower()
    if status not in ALLOWED_DUPLICATE_REVIEW_STATUS:
        raise ValueError(
            "Unsupported duplicate review status. Allowed values: "
            + ", ".join(sorted(ALLOWED_DUPLICATE_REVIEW_STATUS))
        )
    return status


def _build_ops_snapshot(db: Session) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    since_24h = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(minutes=max(1, settings.import_stale_minutes))

    queue_metrics = read_queue_metrics("imports")
    failed_imports_24h = (
        db.query(func.count(StatementImport.id))
        .filter(
            StatementImport.status == "failed",
            StatementImport.updated_at >= since_24h,
        )
        .scalar()
        or 0
    )
    stale_processing_imports = (
        db.query(func.count(StatementImport.id))
        .filter(
            StatementImport.status == "processing",
            StatementImport.updated_at < stale_cutoff,
        )
        .scalar()
        or 0
    )
    pending_duplicate_reviews = (
        db.query(func.count(DuplicateReview.id))
        .filter(DuplicateReview.status == "pending")
        .scalar()
        or 0
    )

    alerts: list[dict] = []
    if queue_metrics is None:
        alerts.append(
            {
                "severity": "critical",
                "code": "queue_unavailable",
                "message": "Queue metrics unavailable. Redis/RQ may be down.",
            }
        )
    else:
        if queue_metrics.queued >= settings.ops_alert_queue_depth_threshold:
            alerts.append(
                {
                    "severity": "warning",
                    "code": "queue_depth_high",
                    "message": "Import queue depth exceeded threshold.",
                    "observed_value": queue_metrics.queued,
                    "threshold": settings.ops_alert_queue_depth_threshold,
                }
            )
        if queue_metrics.failed > 0:
            alerts.append(
                {
                    "severity": "warning",
                    "code": "queue_failed_jobs_present",
                    "message": "Failed jobs exist in RQ registry.",
                    "observed_value": queue_metrics.failed,
                    "threshold": 0,
                }
            )

    if failed_imports_24h >= settings.ops_alert_failed_imports_threshold_24h:
        alerts.append(
            {
                "severity": "warning",
                "code": "failed_imports_24h_high",
                "message": "Import failures in the last 24h exceeded threshold.",
                "observed_value": failed_imports_24h,
                "threshold": settings.ops_alert_failed_imports_threshold_24h,
            }
        )
    if stale_processing_imports >= settings.ops_alert_stale_processing_threshold:
        alerts.append(
            {
                "severity": "warning",
                "code": "stale_processing_imports_high",
                "message": "Stale processing imports exceeded threshold.",
                "observed_value": stale_processing_imports,
                "threshold": settings.ops_alert_stale_processing_threshold,
            }
        )

    return {
        "generated_at": utc_now_iso(),
        "queue": (
            {
                "name": queue_metrics.queue_name,
                "queued": queue_metrics.queued,
                "started": queue_metrics.started,
                "deferred": queue_metrics.deferred,
                "scheduled": queue_metrics.scheduled,
                "failed": queue_metrics.failed,
                "finished": queue_metrics.finished,
                "workers_total": queue_metrics.workers_total,
                "workers_busy": queue_metrics.workers_busy,
            }
            if queue_metrics
            else None
        ),
        "imports": {
            "failed_24h": int(failed_imports_24h),
            "stale_processing": int(stale_processing_imports),
        },
        "duplicate_reviews": {
            "pending": int(pending_duplicate_reviews),
        },
        "alerts": alerts,
    }


@app.post(f"{settings.api_prefix}/imports", response_model=StatementImportResponse)
async def create_import(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> StatementImportResponse:
    user_id = _get_request_user_id(request)
    import_id = str(uuid.uuid4())
    filename = file.filename or f"statement-{import_id}.csv"
    raw_content = await file.read()
    decoded_content = raw_content.decode("utf-8-sig", errors="ignore")

    record = StatementImport(
        id=import_id,
        user_id=user_id if settings.clerk_enabled else None,
        filename=filename,
        status="queued",
    )
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
def create_category(payload: CategoryCreateRequest, request: Request, db: Session = Depends(get_db)) -> CategoryResponse:
    _require_admin(request)
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
    payload: ClassificationRuleCreateRequest, request: Request, db: Session = Depends(get_db)
) -> ClassificationRuleResponse:
    _require_admin(request)
    try:
        normalized_rule_type = _normalize_rule_type(payload.rule_type)
        normalized_category = _resolve_category(payload.category, db, create_if_missing=True)
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
    rule_id: str, payload: ClassificationRuleUpdateRequest, request: Request, db: Session = Depends(get_db)
) -> ClassificationRuleResponse:
    _require_admin(request)
    row = db.get(ClassificationRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Classification rule not found")

    try:
        if payload.rule_type is not None:
            row.rule_type = _normalize_rule_type(payload.rule_type)
        if payload.pattern is not None:
            row.pattern = payload.pattern.strip().lower()
        if payload.category is not None:
            row.category = _resolve_category(payload.category, db, create_if_missing=True)
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
def delete_classification_rule(rule_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    _require_admin(request)
    row = db.get(ClassificationRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Classification rule not found")

    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@app.post(
    f"{settings.api_prefix}/classification-rules/config/save",
    response_model=ClassificationRuleConfigSaveResponse,
)
def save_classification_rules_config(
    request: Request, db: Session = Depends(get_db)
) -> ClassificationRuleConfigSaveResponse:
    _require_admin(request)
    rows = (
        db.query(ClassificationRule)
        .order_by(ClassificationRule.priority.asc(), ClassificationRule.created_at.asc())
        .all()
    )
    payload = [
        {
            "rule_type": row.rule_type,
            "pattern": row.pattern,
            "category": row.category,
            "confidence": float(row.confidence),
            "priority": int(row.priority),
            "is_active": bool(row.is_active),
        }
        for row in rows
    ]
    path = save_rules_config_file(payload)
    return ClassificationRuleConfigSaveResponse(path=str(path), exported_rules=len(payload))


@app.post(
    f"{settings.api_prefix}/classification-rules/config/load",
    response_model=ClassificationRuleConfigLoadResponse,
)
def load_classification_rules_config(
    payload: ClassificationRuleConfigLoadRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ClassificationRuleConfigLoadResponse:
    _require_admin(request)
    file_rules = load_rules_config_file()
    if not file_rules:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid rules found in config file. "
                f"Expected JSON array at {resolve_rules_config_path()}"
            ),
        )

    if payload.replace_existing:
        db.query(ClassificationRule).delete()
        db.commit()

    loaded_count = 0
    for item in file_rules:
        try:
            normalized_rule_type = _normalize_rule_type(item["rule_type"])
            normalized_category = _resolve_category(item["category"], db, create_if_missing=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        row = ClassificationRule(
            rule_type=normalized_rule_type,
            pattern=item["pattern"].strip().lower(),
            category=normalized_category,
            confidence=float(item["confidence"]),
            priority=int(item["priority"]),
            is_active=1 if bool(item.get("is_active", True)) else 0,
        )
        db.add(row)
        loaded_count += 1

    db.commit()
    return ClassificationRuleConfigLoadResponse(
        path=str(resolve_rules_config_path()),
        loaded_rules=loaded_count,
        replaced_existing=payload.replace_existing,
    )


@app.get(f"{settings.api_prefix}/imports/{{import_id}}", response_model=StatementImportResponse)
def get_import(import_id: str, request: Request, db: Session = Depends(get_db)) -> StatementImportResponse:
    user_id = _get_request_user_id(request)
    query = db.query(StatementImport).filter(StatementImport.id == import_id)
    query = _apply_user_scope(query, StatementImport, user_id)
    record = query.one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Import not found")
    record = _sync_import_status(record, db)
    return _to_import_response(record)


@app.get(f"{settings.api_prefix}/duplicate-reviews", response_model=list[DuplicateReviewResponse])
def list_duplicate_reviews(
    request: Request,
    import_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[DuplicateReviewResponse]:
    user_id = _get_request_user_id(request)
    query = db.query(DuplicateReview)
    query = _apply_user_scope(query, DuplicateReview, user_id)
    if import_id:
        query = query.filter(DuplicateReview.source_import_id == import_id)
    if status:
        try:
            normalized_status = _normalize_duplicate_review_status(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        query = query.filter(DuplicateReview.status == normalized_status)

    rows = (
        query.order_by(DuplicateReview.created_at.desc(), DuplicateReview.source_row_number.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_duplicate_review_response(row) for row in rows]


@app.patch(f"{settings.api_prefix}/duplicate-reviews/{{review_id}}", response_model=DuplicateReviewResponse)
def update_duplicate_review(
    review_id: str,
    payload: DuplicateReviewUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DuplicateReviewResponse:
    user_id = _get_request_user_id(request)
    row = (
        _apply_user_scope(db.query(DuplicateReview), DuplicateReview, user_id)
        .filter(DuplicateReview.id == review_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Duplicate review not found")

    try:
        row.status = _normalize_duplicate_review_status(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row.review_note = payload.review_note.strip() if payload.review_note else None
    row.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return _to_duplicate_review_response(row)


@app.post(
    f"{settings.api_prefix}/duplicate-reviews/{{review_id}}/resolve",
    response_model=DuplicateReviewResolveResponse,
)
def resolve_duplicate_review(
    review_id: str,
    payload: DuplicateReviewResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DuplicateReviewResolveResponse:
    user_id = _get_request_user_id(request)
    row = (
        _apply_user_scope(db.query(DuplicateReview), DuplicateReview, user_id)
        .filter(DuplicateReview.id == review_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Duplicate review not found")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Duplicate review is not pending")

    action = payload.action.strip().lower()
    try:
        created_transaction_id = _apply_duplicate_review_action(row=row, action=action, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    return DuplicateReviewResolveResponse(
        action=action,
        status="created_transaction_and_deleted_review" if created_transaction_id else "deleted",
        deleted_review_id=review_id,
        created_transaction_id=created_transaction_id,
    )


@app.post(
    f"{settings.api_prefix}/duplicate-reviews/bulk-resolve",
    response_model=DuplicateReviewBulkResolveResponse,
)
def bulk_resolve_duplicate_reviews(
    payload: DuplicateReviewBulkResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DuplicateReviewBulkResolveResponse:
    user_id = _get_request_user_id(request)
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Bulk resolve requires confirm=true")

    review_ids = list(dict.fromkeys(payload.review_ids))
    requested_count = len(review_ids)
    if requested_count > BULK_DUPLICATE_REVIEW_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resolve more than {BULK_DUPLICATE_REVIEW_MAX} reviews in one request",
        )
    if payload.expected_pending_count != requested_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "expected_pending_count mismatch. "
                "Refresh queue and retry with currently shown record count."
            ),
        )

    action = payload.action.strip().lower()
    rows = (
        _apply_user_scope(db.query(DuplicateReview), DuplicateReview, user_id)
        .filter(DuplicateReview.id.in_(review_ids))
        .all()
    )
    row_by_id = {row.id: row for row in rows}

    processed_count = 0
    deleted_reviews_count = 0
    created_transactions_count = 0
    skipped_missing_count = 0
    skipped_non_pending_count = 0

    for review_id in review_ids:
        row = row_by_id.get(review_id)
        if row is None:
            skipped_missing_count += 1
            continue
        if row.status != "pending":
            skipped_non_pending_count += 1
            continue

        try:
            created_transaction_id = _apply_duplicate_review_action(row=row, action=action, db=db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        processed_count += 1
        deleted_reviews_count += 1
        if created_transaction_id:
            created_transactions_count += 1

    if processed_count > 0:
        db.commit()

    return DuplicateReviewBulkResolveResponse(
        action=action,
        requested_count=requested_count,
        processed_count=processed_count,
        deleted_reviews_count=deleted_reviews_count,
        created_transactions_count=created_transactions_count,
        skipped_missing_count=skipped_missing_count,
        skipped_non_pending_count=skipped_non_pending_count,
    )


@app.get(f"{settings.api_prefix}/transactions", response_model=list[TransactionResponse])
def list_transactions(
    request: Request,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[TransactionResponse]:
    user_id = _get_request_user_id(request)
    query = db.query(Transaction)
    query = _apply_user_scope(query, Transaction, user_id)
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
    request: Request,
    db: Session = Depends(get_db),
) -> RecategorizeTransactionsResponse:
    user_id = _get_request_user_id(request)
    rules = load_active_rules(db)
    if not rules:
        raise HTTPException(status_code=400, detail="No active classification rules found.")

    query = db.query(Transaction)
    query = _apply_user_scope(query, Transaction, user_id)
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
    payload: ManualTransactionCreateRequest, request: Request, db: Session = Depends(get_db)
) -> TransactionResponse:
    user_id = _get_request_user_id(request)
    try:
        normalized_category = _resolve_category(payload.category, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    manual_import = _get_or_create_manual_import(db, user_id)

    merchant = (payload.merchant_normalized or "").strip()
    if not merchant:
        merchant = payload.description_raw.strip()[:100]

    dedupe_fingerprint = build_dedupe_fingerprint(
        transaction_date=payload.transaction_date,
        merchant_name=merchant,
        amount=payload.amount,
        direction=payload.direction,
        user_scope=user_id or "",
    )
    existing = db.execute(
        select(Transaction.id).where(
            _build_user_condition(Transaction, user_id),
            Transaction.dedupe_fingerprint == dedupe_fingerprint,
        )
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
            _build_user_condition(Transaction, user_id),
            Transaction.transaction_date == payload.transaction_date,
            func.lower(Transaction.merchant_normalized) == merchant.lower(),
            func.round(cast(Transaction.amount, Numeric(18, 2)), 2) == round(payload.amount, 2),
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
        user_id=user_id if settings.clerk_enabled else None,
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
    transaction_id: str, payload: CategoryUpdateRequest, request: Request, db: Session = Depends(get_db)
) -> TransactionResponse:
    user_id = _get_request_user_id(request)
    txn = (
        _apply_user_scope(db.query(Transaction), Transaction, user_id)
        .filter(Transaction.id == transaction_id)
        .one_or_none()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    try:
        normalized = _resolve_category(payload.category, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    txn.category = normalized
    txn.category_confidence = 1.0
    db.commit()
    db.refresh(txn)
    return _to_transaction_response(txn)


@app.get(f"{settings.api_prefix}/analytics/categories", response_model=list[CategorySpend])
def analytics_by_category(
    request: Request,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CategorySpend]:
    user_id = _get_request_user_id(request)
    query = db.query(Transaction.category, func.sum(Transaction.amount)).filter(Transaction.direction == "debit")
    query = query.filter(_build_user_condition(Transaction, user_id))
    if start_date is not None:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(Transaction.transaction_date <= end_date)
    rows = query.group_by(Transaction.category).all()
    return [CategorySpend(category=category or "uncategorized", total=float(total or 0.0)) for category, total in rows]


@app.get(f"{settings.api_prefix}/analytics/merchants", response_model=list[MerchantSpend])
def analytics_by_merchant(
    request: Request,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[MerchantSpend]:
    user_id = _get_request_user_id(request)
    query = db.query(Transaction.merchant_normalized, func.sum(Transaction.amount)).filter(
        Transaction.direction == "debit"
    )
    query = query.filter(_build_user_condition(Transaction, user_id))
    if start_date is not None:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(Transaction.transaction_date <= end_date)
    rows = query.group_by(Transaction.merchant_normalized).all()
    return [MerchantSpend(merchant=merchant or "unknown", total=float(total or 0.0)) for merchant, total in rows]


@app.post(f"{settings.api_prefix}/insights/generate", response_model=InsightReportResponse)
def generate_insights(
    payload: InsightGenerateRequest, request: Request, db: Session = Depends(get_db)
) -> InsightReportResponse:
    user_id = _get_request_user_id(request)
    query = db.query(Transaction)
    query = _apply_user_scope(query, Transaction, user_id)
    if payload.start_date is not None:
        query = query.filter(Transaction.transaction_date >= payload.start_date)
    if payload.end_date is not None:
        query = query.filter(Transaction.transaction_date <= payload.end_date)

    transactions = query.all()
    if not transactions:
        raise HTTPException(status_code=400, detail="No transactions found for selected range")

    insight_payload = build_spend_insight(transactions)

    report = InsightReport(
        user_id=user_id if settings.clerk_enabled else None,
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
def get_insight(insight_id: str, request: Request, db: Session = Depends(get_db)) -> InsightReportResponse:
    user_id = _get_request_user_id(request)
    report = (
        _apply_user_scope(db.query(InsightReport), InsightReport, user_id)
        .filter(InsightReport.id == insight_id)
        .one_or_none()
    )
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


@app.get(f"{settings.api_prefix}/ops/metrics")
def get_ops_metrics(request: Request, db: Session = Depends(get_db)) -> dict:
    if not settings.ops_metrics_enabled:
        raise HTTPException(status_code=404, detail="Ops metrics are disabled")
    _ = _get_request_user_id(request)
    snapshot = _build_ops_snapshot(db)
    alerts = snapshot.get("alerts", [])
    if alerts:
        logger.warning(
            "ops_alerts_triggered",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "alert_count": len(alerts),
                "alert_codes": [item.get("code") for item in alerts],
            },
        )
    return snapshot


@app.get(f"{settings.api_prefix}/ops/alerts")
def get_ops_alerts(request: Request, db: Session = Depends(get_db)) -> dict:
    if not settings.ops_metrics_enabled:
        raise HTTPException(status_code=404, detail="Ops metrics are disabled")
    _ = _get_request_user_id(request)
    snapshot = _build_ops_snapshot(db)
    alerts = snapshot.get("alerts", [])
    return {
        "generated_at": snapshot["generated_at"],
        "count": len(alerts),
        "alerts": alerts,
    }


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}

import csv
import io
from datetime import date, datetime

from dateutil import parser as date_parser
from sqlalchemy import Numeric, cast, func, select

from .classification_engine import classify_with_rules, load_active_rules
from .db import SessionLocal
from .dedupe import build_dedupe_fingerprint
from .models import DuplicateReview, StatementImport, Transaction, UploadedFile


def _pick_value(row: dict[str, str], candidates: list[str]) -> str:
    lowered = {k.strip().lower(): v for k, v in row.items() if k is not None}
    for candidate in candidates:
        value = lowered.get(candidate)
        if value:
            return value.strip()
    return ""


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date_parser.parse(value, dayfirst=False).date()
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_amount(value: str) -> float | None:
    if not value:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _merchant_from_description(description: str) -> str:
    cleaned = " ".join(description.split()).strip()
    if not cleaned:
        return "unknown"
    return cleaned[:100]


def _parse_row(row: dict[str, str], classification_rules, user_scope: str) -> dict | None:
    date_str = _pick_value(row, ["date", "transaction date", "posted date", "posting date"])
    description = _pick_value(row, ["description", "memo", "merchant", "name", "details"])
    source_category = _pick_value(row, ["category", "type", "transaction type"])
    amount_raw = _pick_value(row, ["amount", "transaction amount"])
    debit_raw = _pick_value(row, ["debit", "withdrawal"])
    credit_raw = _pick_value(row, ["credit", "deposit"])

    txn_date = _parse_date(date_str)
    direction = "debit"

    debit_amount = _parse_amount(debit_raw)
    credit_amount = _parse_amount(credit_raw)

    # Strict split-column interpretation:
    # - Debit populated => debit transaction
    # - Credit populated => credit transaction
    # - Both populated => invalid row format
    if debit_amount is not None and debit_amount != 0 and (credit_amount is None or credit_amount == 0):
        amount = abs(debit_amount)
        direction = "debit"
    elif credit_amount is not None and credit_amount != 0 and (debit_amount is None or debit_amount == 0):
        amount = abs(credit_amount)
        direction = "credit"
    elif debit_amount is not None and debit_amount != 0 and credit_amount is not None and credit_amount != 0:
        raise ValueError("Both debit and credit columns are populated for a row")
    else:
        parsed_amount = _parse_amount(amount_raw)
        if parsed_amount is None:
            return None
        if parsed_amount < 0:
            amount = abs(parsed_amount)
            direction = "debit"
        else:
            amount = abs(parsed_amount)
            direction = "credit"

    merchant = _merchant_from_description(description)
    category, confidence = classify_with_rules(
        rules=classification_rules,
        description=description,
        merchant=merchant,
        source_category=source_category,
    )
    fingerprint = build_dedupe_fingerprint(
        transaction_date=txn_date,
        merchant_name=merchant,
        amount=amount,
        direction=direction,
        user_scope=user_scope,
    )

    return {
        "transaction_date": txn_date,
        "description_raw": description or "unknown transaction",
        "merchant_normalized": merchant,
        "amount": amount,
        "currency": "USD",
        "direction": direction,
        "category": category,
        "category_confidence": confidence,
        "dedupe_fingerprint": fingerprint,
    }


def _queue_duplicate_review(
    session,
    import_id: str,
    source_row_number: int,
    duplicate_scope: str,
    duplicate_reason: str,
    parsed_row: dict,
    user_id: str | None = None,
    matched_transaction_id: str | None = None,
) -> None:
    session.add(
        DuplicateReview(
            user_id=user_id,
            source_import_id=import_id,
            source_row_number=source_row_number,
            duplicate_scope=duplicate_scope,
            duplicate_reason=duplicate_reason,
            matched_transaction_id=matched_transaction_id,
            transaction_date=parsed_row["transaction_date"],
            description_raw=parsed_row["description_raw"],
            merchant_normalized=parsed_row["merchant_normalized"],
            amount=parsed_row["amount"],
            currency=parsed_row["currency"],
            direction=parsed_row["direction"],
            category=parsed_row["category"],
            category_confidence=parsed_row["category_confidence"],
            dedupe_fingerprint=parsed_row["dedupe_fingerprint"],
            status="pending",
        )
    )


def process_import_job(import_id: str) -> None:
    session = SessionLocal()
    try:
        record = session.get(StatementImport, import_id)
        if record is None:
            return

        record.status = "processing"
        record.error_message = None
        record.processing_started_at = datetime.utcnow()
        record.finished_at = None
        session.commit()

        uploaded_file = session.execute(
            select(UploadedFile).where(UploadedFile.import_id == import_id)
        ).scalar_one_or_none()
        if uploaded_file is None:
            raise ValueError("Uploaded CSV content not found for import")

        total_rows = 0
        processed_rows = 0
        seen_fingerprints: set[str] = set()
        classification_rules = load_active_rules(session)
        user_scope = (record.user_id or "").strip()
        user_condition = (
            Transaction.user_id.is_(None)
            if record.user_id is None
            else Transaction.user_id == record.user_id
        )

        with io.StringIO(uploaded_file.content_text) as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                total_rows += 1
                parsed = _parse_row(
                    row=row,
                    classification_rules=classification_rules,
                    user_scope=user_scope,
                )
                if parsed is None:
                    continue
                if parsed["dedupe_fingerprint"] in seen_fingerprints:
                    _queue_duplicate_review(
                        session=session,
                        import_id=import_id,
                        source_row_number=total_rows,
                        duplicate_scope="same_import",
                        duplicate_reason="fingerprint_match",
                        parsed_row=parsed,
                        user_id=record.user_id,
                        matched_transaction_id=None,
                    )
                    continue

                exists_stmt = select(Transaction.id).where(
                    user_condition,
                    Transaction.dedupe_fingerprint == parsed["dedupe_fingerprint"]
                )
                matched_existing_id = session.execute(exists_stmt).scalar_one_or_none()
                if matched_existing_id is not None:
                    _queue_duplicate_review(
                        session=session,
                        import_id=import_id,
                        source_row_number=total_rows,
                        duplicate_scope="existing_data",
                        duplicate_reason="fingerprint_match",
                        parsed_row=parsed,
                        user_id=record.user_id,
                        matched_transaction_id=matched_existing_id,
                    )
                    continue

                date_condition = (
                    Transaction.transaction_date.is_(None)
                    if parsed["transaction_date"] is None
                    else Transaction.transaction_date == parsed["transaction_date"]
                )
                natural_key_exists_stmt = select(Transaction.id).where(
                    user_condition,
                    date_condition,
                    func.lower(Transaction.merchant_normalized)
                    == parsed["merchant_normalized"].strip().lower(),
                    func.round(cast(Transaction.amount, Numeric(18, 2)), 2)
                    == round(float(parsed["amount"]), 2),
                    Transaction.direction == parsed["direction"],
                )
                matched_natural_key_id = session.execute(natural_key_exists_stmt).scalar_one_or_none()
                if matched_natural_key_id is not None:
                    _queue_duplicate_review(
                        session=session,
                        import_id=import_id,
                        source_row_number=total_rows,
                        duplicate_scope="existing_data",
                        duplicate_reason="natural_key_match",
                        parsed_row=parsed,
                        user_id=record.user_id,
                        matched_transaction_id=matched_natural_key_id,
                    )
                    continue

                txn = Transaction(
                    user_id=record.user_id,
                    source_import_id=import_id,
                    transaction_date=parsed["transaction_date"],
                    description_raw=parsed["description_raw"],
                    merchant_normalized=parsed["merchant_normalized"],
                    amount=parsed["amount"],
                    currency=parsed["currency"],
                    direction=parsed["direction"],
                    category=parsed["category"],
                    category_confidence=parsed["category_confidence"],
                    dedupe_fingerprint=parsed["dedupe_fingerprint"],
                )
                session.add(txn)
                seen_fingerprints.add(parsed["dedupe_fingerprint"])
                processed_rows += 1

                if total_rows % 100 == 0:
                    record.total_rows = total_rows
                    record.processed_rows = processed_rows
                    session.commit()

        record.status = "completed"
        record.total_rows = total_rows
        record.processed_rows = processed_rows
        record.finished_at = datetime.utcnow()
        session.commit()
    except Exception as exc:  # noqa: BLE001
        # Roll back first so session can safely query/update the import record.
        session.rollback()
        try:
            record = session.get(StatementImport, import_id)
            if record is not None:
                record.status = "failed"
                record.finished_at = datetime.utcnow()
                record.error_message = f"{exc.__class__.__name__}: {exc}"
                session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
    finally:
        session.close()

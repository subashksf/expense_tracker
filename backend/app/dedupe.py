import hashlib
from datetime import date


def normalize_merchant_name(merchant_name: str) -> str:
    cleaned = " ".join(merchant_name.lower().split()).strip()
    return cleaned or "unknown"


def build_dedupe_fingerprint(
    transaction_date: date | None,
    merchant_name: str,
    amount: float,
    direction: str,
    user_scope: str = "",
) -> str:
    date_part = transaction_date.isoformat() if transaction_date else ""
    merchant_part = normalize_merchant_name(merchant_name)
    amount_part = f"{abs(amount):.2f}"
    direction_part = direction.strip().lower()
    scope_part = user_scope.strip().lower()
    raw = f"{scope_part}|{date_part}|{merchant_part}|{amount_part}|{direction_part}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

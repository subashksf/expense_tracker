from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import ClassificationRule


@dataclass
class Rule:
    id: str
    rule_type: str
    pattern: str
    category: str
    confidence: float
    priority: int
    is_active: bool


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split()).strip()


def load_active_rules(db: Session) -> list[Rule]:
    rows = (
        db.query(ClassificationRule)
        .filter(ClassificationRule.is_active == 1)
        .order_by(ClassificationRule.priority.asc(), ClassificationRule.created_at.asc())
        .all()
    )
    return [
        Rule(
            id=row.id,
            rule_type=row.rule_type,
            pattern=_normalize_text(row.pattern),
            category=row.category,
            confidence=float(row.confidence),
            priority=int(row.priority),
            is_active=bool(row.is_active),
        )
        for row in rows
    ]


def classify_with_rules(
    rules: list[Rule],
    description: str,
    merchant: str,
    source_category: str,
) -> tuple[str, float]:
    description_normalized = _normalize_text(description)
    merchant_normalized = _normalize_text(merchant)
    source_category_normalized = _normalize_text(source_category)
    combined_text = f"{description_normalized} {merchant_normalized}".strip()

    for rule in rules:
        if not rule.pattern:
            continue
        if rule.rule_type == "source_category_contains":
            if rule.pattern in source_category_normalized:
                return rule.category, rule.confidence
            continue
        if rule.rule_type == "merchant_exact":
            if merchant_normalized == rule.pattern:
                return rule.category, rule.confidence
            continue
        if rule.rule_type == "merchant_contains":
            if rule.pattern in merchant_normalized:
                return rule.category, rule.confidence
            continue
        if rule.rule_type == "description_contains":
            if rule.pattern in description_normalized:
                return rule.category, rule.confidence
            continue
        if rule.rule_type == "text_contains":
            if rule.pattern in combined_text:
                return rule.category, rule.confidence
            continue

    return "uncategorized", 0.5

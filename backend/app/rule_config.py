import json
from pathlib import Path
from typing import Any

from .config import settings


def resolve_rules_config_path() -> Path:
    configured = Path(settings.rules_config_path)
    if configured.is_absolute():
        return configured
    project_root = Path(__file__).resolve().parent.parent
    return (project_root / configured).resolve()


def _normalize_rule_entry(raw: dict[str, Any]) -> dict[str, Any]:
    raw_active = raw.get("is_active", True)
    if isinstance(raw_active, str):
        normalized_active = raw_active.strip().lower() in {"1", "true", "yes", "y"}
    else:
        normalized_active = bool(raw_active)
    return {
        "rule_type": str(raw.get("rule_type", "")).strip().lower(),
        "pattern": str(raw.get("pattern", "")).strip().lower(),
        "category": str(raw.get("category", "")).strip().lower(),
        "confidence": float(raw.get("confidence", 0.8)),
        "priority": int(raw.get("priority", 100)),
        "is_active": normalized_active,
    }


def load_rules_config_file() -> list[dict[str, Any]]:
    path = resolve_rules_config_path()
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    if not isinstance(parsed, list):
        raise ValueError("Rules config file must contain a JSON array")

    rows: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_rule_entry(item)
        if not normalized["rule_type"] or not normalized["pattern"] or not normalized["category"]:
            continue
        rows.append(normalized)
    return rows


def save_rules_config_file(rules: list[dict[str, Any]]) -> Path:
    normalized = [_normalize_rule_entry(item) for item in rules]
    output = [
        {
            "rule_type": row["rule_type"],
            "pattern": row["pattern"],
            "category": row["category"],
            "confidence": row["confidence"],
            "priority": row["priority"],
            "is_active": row["is_active"],
        }
        for row in normalized
        if row["rule_type"] and row["pattern"] and row["category"]
    ]

    path = resolve_rules_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")
    return path

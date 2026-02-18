from collections import defaultdict

from .models import Transaction


def build_spend_insight(transactions: list[Transaction]) -> dict:
    total_spend = 0.0
    by_category: dict[str, float] = defaultdict(float)
    by_merchant: dict[str, float] = defaultdict(float)

    for txn in transactions:
        if txn.direction != "debit":
            continue
        total_spend += txn.amount
        by_category[txn.category] += txn.amount
        by_merchant[txn.merchant_normalized] += txn.amount

    top_categories = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:3]
    top_merchants = sorted(by_merchant.items(), key=lambda x: x[1], reverse=True)[:5]

    savings_actions = []
    for category, amount in top_categories:
        suggested_cut = round(amount * 0.1, 2)
        savings_actions.append(
            {
                "category": category,
                "current_spend": round(amount, 2),
                "suggested_reduction_pct": 10,
                "suggested_monthly_savings": suggested_cut,
                "reason": f"{category} is one of your top spending categories.",
            }
        )

    summary = (
        f"Total debit spend in selected period is ${total_spend:,.2f}. "
        f"Top categories: {', '.join(cat for cat, _ in top_categories) or 'none'}."
    )

    # This is a deterministic placeholder. Replace with an LLM call once the
    # prompt + JSON schema contract is finalized.
    return {
        "summary": summary,
        "top_spend_drivers": [{"category": c, "amount": round(a, 2)} for c, a in top_categories],
        "top_merchants": [{"merchant": m, "amount": round(a, 2)} for m, a in top_merchants],
        "potential_savings_actions": savings_actions,
        "risk_flags": [],
        "confidence": 0.72,
    }

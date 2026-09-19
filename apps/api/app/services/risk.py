from decimal import Decimal


def score_payment(amount: Decimal, has_channel: bool) -> tuple[int, list[str]]:
    score, reasons = 0, []
    if amount >= Decimal("100000"):
        score += 40
        reasons.append("high_amount")
    if not has_channel:
        score += 20
        reasons.append("no_preselected_channel")
    return score, reasons

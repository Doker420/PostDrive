EVENT_TEMPLATES = {
    "payment.created": "FlowPay: создан платеж {payment_id}\nСумма: {amount} {currency}",
    "payment.succeeded": "FlowPay: платеж подтверждён ✅\nID: {payment_id}\nСумма: {amount} {currency}",
    "payment.failed": "FlowPay: платеж отклонён ❌\nID: {payment_id}\nСумма: {amount} {currency}",
    "payout.completed": "FlowPay: выплата отправлена ✅\nID: {payout_id}\nСумма: {amount} {currency}",
    "payout.failed": "FlowPay: ошибка выплаты ⚠️\nID: {payout_id}",
}


def render_event(event_type: str, **values: object) -> str:
    template = EVENT_TEMPLATES.get(event_type, f"FlowPay: {event_type}")
    return template.format(**values)

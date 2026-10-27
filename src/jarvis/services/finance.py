"""Private monthly spending view derived from recognized bank notification emails."""

from __future__ import annotations

import calendar
import csv
import io
import re
import statistics
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from jarvis.services.mail_providers import MailError

TZ = ZoneInfo("America/Guayaquil")

CATEGORIES = {
    "alimentacion": "Alimentación",
    "transporte": "Transporte",
    "compras": "Compras",
    "entretenimiento": "Entretenimiento",
    "salud": "Salud",
    "servicios": "Servicios",
    "educacion": "Educación",
    "donaciones": "Donaciones",
    "transferencias": "Transferencias",
    "efectivo": "Efectivo",
    "otros": "Otros",
}

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_BANK_SENDERS = {
    "bancaenlinea@produbanco.com": "Produbanco",
    "banco@pichincha.com": "Banco Pichincha",
    "documentoselectronicos@pichincha.com": "Banco Pichincha",
}

_MERCHANT_NAMES = (
    (("kfc",), "KFC"),
    (("mcdonald",), "McDonald's"),
    (("uber",), "Uber"),
    (("rappi",), "Rappi"),
    (("spotify",), "Spotify"),
    (("netflix",), "Netflix"),
    (("steam",), "Steam"),
    (("amazon",), "Amazon"),
    (("mercado libre", "mercadolibre"), "Mercado Libre"),
    (("fybeca",), "Fybeca"),
)


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(character for character in text if not unicodedata.combining(character))


def _compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sender_address(value: object) -> str:
    _name, address = parseaddr(str(value or ""))
    return address.strip().casefold()


def _cents(value: str) -> int | None:
    raw = re.sub(r"[^0-9.,]", "", value)
    if not raw:
        return None
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[1]
        raw = raw.replace(".", "").replace(",", "." if len(tail) <= 2 else "")
    elif "." in raw and len(raw.rsplit(".", 1)[1]) > 2:
        raw = raw.replace(".", "")
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    if amount <= 0 or amount > Decimal("1000000000"):
        return None
    return int(amount * 100)


def _money(cents: int) -> str:
    return f"{Decimal(cents) / Decimal(100):.2f}"


def _setting_cents(value: object, *, field: str) -> int:
    raw = str(value or "0").strip()
    if not re.fullmatch(r"\d{1,8}(?:[.,]\d{1,2})?", raw):
        raise MailError(f"{field} debe ser un monto positivo con hasta dos decimales")
    amount = Decimal(raw.replace(",", ".")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount < 0 or amount > Decimal("10000000"):
        raise MailError(f"{field} está fuera del rango permitido")
    return int(amount * 100)


def _merchant_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalized(value)).strip()[:120]


def _merchant_name(value: object) -> str:
    """Remove common processor/location noise without guessing unknown businesses."""

    compact = _compact(value)
    normalized = _normalized(compact)
    for needles, label in _MERCHANT_NAMES:
        if any(needle in normalized for needle in needles):
            return label
    cleaned = re.sub(
        r"(?i)^(?:payphone|datafast|medianet|paypal|google\s*\*)[\s*:/-]+",
        "",
        compact,
    )
    cleaned = re.sub(r"(?i)\s+(?:quito|guayaquil|ecuador|ec)$", "", cleaned).strip(" -*/")
    return (cleaned or compact or "Comercio")[:100]


def _shift_month(value: datetime, offset: int) -> datetime:
    absolute = value.year * 12 + value.month - 1 + offset
    year, month_index = divmod(absolute, 12)
    return datetime(year, month_index + 1, 1, tzinfo=value.tzinfo)


def _money_field(body: str, label: str) -> int | None:
    match = re.search(
        rf"\b{re.escape(label)}\s*:\s*(?:USD\s*|US\$\s*|\$\s*)?([0-9][0-9.,]*)",
        body,
        re.IGNORECASE,
    )
    return _cents(match.group(1)) if match else None


def _field(body: str, label: str, endings: tuple[str, ...]) -> str:
    end = "|".join(re.escape(item) for item in endings)
    match = re.search(
        rf"\b{re.escape(label)}\s*:\s*(.*?)(?=\s*(?:{end})\s*:|$)",
        body,
        re.IGNORECASE,
    )
    return _compact(match.group(1))[:160] if match else ""


def _received(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(TZ)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(TZ)


def _occurred(body: str, fallback: datetime) -> datetime:
    numeric = re.search(
        r"\bFecha(?: y Hora(?: de Proceso)?| de Proceso)?\s*:\s*"
        r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::\d{2})?)?",
        body,
        re.IGNORECASE,
    )
    if numeric:
        try:
            return datetime(
                int(numeric[3]),
                int(numeric[2]),
                int(numeric[1]),
                int(numeric[4] or 12),
                int(numeric[5] or 0),
                tzinfo=TZ,
            )
        except ValueError:
            return fallback
    named = re.search(
        r"\bFecha y Hora(?: de Proceso)?\s*:\s*(\d{1,2})/([A-Za-zÁÉÍÓÚáéíóúñÑ]+)/(\d{4})"
        r"(?:\s+(\d{1,2}):(\d{2}))?",
        body,
        re.IGNORECASE,
    )
    if named:
        month = _MONTHS.get(_normalized(named[2]))
        if month:
            try:
                return datetime(
                    int(named[3]),
                    month,
                    int(named[1]),
                    int(named[4] or 12),
                    int(named[5] or 0),
                    tzinfo=TZ,
                )
            except ValueError:
                pass
    return fallback


def _category(kind: str, merchant: str, description: str) -> str:
    if kind == "transfer":
        return "transferencias"
    if kind == "withdrawal":
        return "efectivo"
    text = _normalized(merchant + " " + description)
    groups = (
        ("donaciones", ("whydonate", "donacion", "fundacion")),
        ("salud", ("fybeca", "farmacia", "medic", "clinica", "hospital")),
        (
            "alimentacion",
            ("kfc", "cajun", "food", "restaur", "rappi", "mcdonald", "cafe", "listo"),
        ),
        ("transporte", ("uber", "cabify", "estacionamiento", "gasolin", "petro", "parqueo")),
        (
            "entretenimiento",
            ("steam", "epic games", "playstation", "xbox", "netflix", "spotify", "cine"),
        ),
        ("educacion", ("universidad", "curso", "udemy", "coursera", "libro")),
        ("servicios", ("internet", "telefono", "energia", "agua", "servicio", "suscripcion")),
        ("compras", ("amazon", "mercado libre", "fantasias", "tienda", "store")),
    )
    for name, words in groups:
        if any(word in text for word in words):
            return name
    return "otros"


def _transaction(message: dict[str, object]) -> dict[str, object] | None:
    sender = _sender_address(message.get("sender"))
    bank = _BANK_SENDERS.get(sender)
    if not bank:
        return None
    body = _compact(message.get("body"))
    normalized = _normalized(body)
    fallback = _received(message.get("received"))
    occurred = _occurred(body, fallback)
    amount = None
    kind = ""
    direction = "expense"
    merchant = ""
    description = ""
    confidence = 0.0
    needs_review = False

    if sender == "bancaenlinea@produbanco.com":
        if "transaccion: consumo tarjeta de debito produbanco" in normalized:
            amount = _money_field(body, "Valor")
            kind = "purchase"
            merchant = _field(body, "Establecimiento", ("Cuenta Débito", "Atentamente"))
            description = "Consumo con tarjeta de débito"
            confidence = 0.99
        elif "transaccion: transferencia acreditada produbanco" in normalized:
            amount = _money_field(body, "Monto")
            kind = "transfer"
            beneficiary = _field(body, "Beneficiario", ("Banco Beneficiario",))
            description = _field(body, "Descripción", ("Canal", "Referencia"))
            merchant = description or beneficiary or "Transferencia enviada"
            confidence = 0.97
            needs_review = True
        elif "transaccion: retiro de efectivo produbanco en cajero automatico" in normalized:
            amount = _money_field(body, "Monto")
            kind = "withdrawal"
            merchant = _field(body, "Cajero", ("Si no realizaste", "Atentamente"))
            description = "Retiro de efectivo"
            confidence = 0.99
        elif "transaccion: acreditacion de intereses" in normalized:
            amount = _money_field(body, "Ganaste")
            kind = "interest"
            direction = "income"
            merchant = "Intereses FlexiAhorro"
            description = "Acreditación de intereses"
            confidence = 0.99
    elif sender == "banco@pichincha.com" and (
        "transferencia pago realizado correctamente" in normalized
    ):
        amount = _money_field(body, "Monto")
        kind = "transfer"
        beneficiary = _field(body, "Nombre del beneficiario", ("Identificación beneficiario",))
        description = _field(body, "Descripción", ("Número de documento", "Si no has"))
        merchant = description or beneficiary or "Transferencia enviada"
        confidence = 0.97
        needs_review = True

    if not amount or not kind:
        return None
    raw_merchant = merchant or bank
    merchant = _merchant_name(raw_merchant)
    category = _category(kind, merchant, description)
    return {
        "id": str(message["id"]),
        "version": str(message["version"]),
        "mail_id": str(message["id"]),
        "account": str(message.get("email") or ""),
        "bank": bank,
        "occurred_at": occurred.isoformat(),
        "received_at": fallback.isoformat(),
        "amount": _money(amount),
        "amount_cents": amount,
        "currency": "USD",
        "direction": direction,
        "kind": kind,
        "merchant": merchant,
        "merchant_raw": raw_merchant,
        "merchant_key": _merchant_key(raw_merchant),
        "description": description,
        "category": category,
        "category_label": CATEGORIES[category],
        "confidence": confidence,
        "needs_review": needs_review,
        "included": True,
        "subject": str(message.get("subject") or ""),
        "url": str(message.get("url") or ""),
    }


def _looks_unparsed(message: dict[str, object]) -> bool:
    sender = _sender_address(message.get("sender"))
    if sender not in _BANK_SENDERS:
        return False
    text = _normalized(message.get("body"))
    ignored = (
        "clave temporal",
        "ingreso app movil",
        "ingreso exitoso",
        "creacion de contacto",
        "aporte mensual programado",
    )
    return not any(item in text for item in ignored) and (
        "transaccion:" in text or "pago realizado correctamente" in text
    )


def _month_bounds(month: str | None) -> tuple[datetime, datetime, datetime]:
    now = datetime.now(TZ)
    if month:
        if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", month):
            raise MailError("El mes debe tener el formato AAAA-MM")
        year, number = (int(part) for part in month.split("-"))
        start = datetime(year, number, 1, tzinfo=TZ)
    else:
        start = datetime(now.year, now.month, 1, tzinfo=TZ)
    end = (
        datetime(start.year + 1, 1, 1, tzinfo=TZ)
        if start.month == 12
        else datetime(start.year, start.month + 1, 1, tzinfo=TZ)
    )
    previous = (
        datetime(start.year - 1, 12, 1, tzinfo=TZ)
        if start.month == 1
        else datetime(start.year, start.month - 1, 1, tzinfo=TZ)
    )
    return start, end, previous


class FinanceTracker:
    def __init__(self, mail_store, organizer_store):
        self.mail_store = mail_store
        self.store = organizer_store

    def _transactions(self, since: datetime, until: datetime):
        rows = self.mail_store.archived_messages(
            since=since.astimezone(UTC).isoformat(),
            until=until.astimezone(UTC).isoformat(),
            limit=10_000,
        )
        transactions = []
        unparsed = []
        for row in rows:
            transaction = _transaction(row)
            if transaction is None:
                if _looks_unparsed(row):
                    unparsed.append(_received(row.get("received")))
                continue
            alias = self.store.get("finance_merchant_alias", str(transaction["merchant_key"]), {})
            if alias.get("merchant"):
                transaction["merchant"] = str(alias["merchant"])
            override = self.store.get("finance_override", transaction["id"], {})
            if override and override.get("version") == transaction["version"]:
                category = override.get("category", transaction["category"])
                if category in CATEGORIES:
                    transaction["category"] = category
                    transaction["category_label"] = CATEGORIES[category]
                transaction["included"] = bool(override.get("included", True))
                if override.get("merchant"):
                    transaction["merchant"] = str(override["merchant"])
                transaction["needs_review"] = False
                transaction["reviewed"] = True
            else:
                transaction["reviewed"] = False
            transactions.append(transaction)
        return transactions, unparsed

    def _budgets(self) -> dict[str, dict[str, object]]:
        return {
            str(item.get("category")): item
            for item in self.store.list("finance_budget")
            if item.get("category") in {*CATEGORIES, "total"}
        }

    @staticmethod
    def _recurring(transactions: list[dict[str, object]]) -> list[dict[str, object]]:
        grouped: dict[str, list[dict[str, object]]] = {}
        for item in transactions:
            if item["included"] and item["direction"] == "expense" and item["kind"] == "purchase":
                grouped.setdefault(str(item["merchant"]).casefold(), []).append(item)
        result = []
        for items in grouped.values():
            items.sort(key=lambda item: str(item["occurred_at"]))
            dated = [datetime.fromisoformat(str(item["occurred_at"])) for item in items]
            unique_days = sorted({value.date() for value in dated})
            if len(unique_days) < 2:
                continue
            intervals = [
                (right - left).days
                for left, right in zip(unique_days, unique_days[1:], strict=False)
            ]
            typical_interval = int(round(statistics.median(intervals)))
            if not 20 <= typical_interval <= 45:
                continue
            amounts = [int(item["amount_cents"]) for item in items]
            typical_amount = int(round(statistics.median(amounts)))
            if typical_amount <= 0 or max(amounts) > typical_amount * 1.6:
                continue
            last = items[-1]
            next_due = datetime.fromisoformat(str(last["occurred_at"])) + timedelta(
                days=typical_interval
            )
            result.append(
                {
                    "merchant": last["merchant"],
                    "category": last["category"],
                    "category_label": last["category_label"],
                    "monthly_estimate": _money(typical_amount),
                    "occurrences": len(unique_days),
                    "last_charge": str(last["occurred_at"]),
                    "next_estimated": next_due.date().isoformat(),
                    "confidence": "high" if len(unique_days) >= 3 else "medium",
                }
            )
        result.sort(key=lambda item: Decimal(str(item["monthly_estimate"])), reverse=True)
        return result[:20]

    @staticmethod
    def _alerts(
        current: list[dict[str, object]], history: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        by_merchant: dict[str, list[int]] = {}
        by_category: dict[str, list[int]] = {}
        for item in history:
            if item["included"] and item["direction"] == "expense":
                by_merchant.setdefault(str(item["merchant"]).casefold(), []).append(
                    int(item["amount_cents"])
                )
                by_category.setdefault(str(item["category"]), []).append(int(item["amount_cents"]))
        alerts = []
        for item in current:
            if not item["included"] or item["direction"] != "expense" or item["kind"] != "purchase":
                continue
            amount = int(item["amount_cents"])
            merchant_history = by_merchant.get(str(item["merchant"]).casefold(), [])
            category_history = by_category.get(str(item["category"]), [])
            baseline = 0
            reason = ""
            if len(merchant_history) >= 3:
                baseline = int(statistics.median(merchant_history))
                if amount >= max(5_000, int(baseline * 1.8)):
                    reason = "supera claramente el gasto habitual en este comercio"
            elif len(category_history) >= 5:
                baseline = int(statistics.median(category_history))
                if amount >= max(10_000, int(baseline * 2.5)):
                    reason = "es inusual frente a otros movimientos de esta categoría"
            elif amount >= 25_000:
                reason = "es una compra alta sin historial suficiente para compararla"
            if reason:
                alerts.append(
                    {
                        "transaction_id": item["id"],
                        "merchant": item["merchant"],
                        "amount": item["amount"],
                        "occurred_at": item["occurred_at"],
                        "reason": reason,
                        "baseline": _money(baseline) if baseline else None,
                    }
                )
        alerts.sort(key=lambda item: Decimal(str(item["amount"])), reverse=True)
        return alerts[:20]

    def summary(self, month: str | None = None):
        start, end, previous = _month_bounds(month)
        history_start = _shift_month(start, -6)
        transactions, unparsed = self._transactions(history_start, end)
        current_unparsed = sum(1 for received in unparsed if start <= received < end)
        current = [
            item
            for item in transactions
            if start <= datetime.fromisoformat(str(item["occurred_at"])) < end
        ]
        prior = [
            item
            for item in transactions
            if previous <= datetime.fromisoformat(str(item["occurred_at"])) < start
        ]
        older = [
            item
            for item in transactions
            if history_start <= datetime.fromisoformat(str(item["occurred_at"])) < start
        ]

        def total(items, *, direction="expense", kind=None):
            return sum(
                int(item["amount_cents"])
                for item in items
                if item["included"]
                and item["direction"] == direction
                and (kind is None or item["kind"] == kind)
            )

        spent = total(current)
        prior_spent = total(prior)
        category_totals: dict[str, dict[str, int]] = {}
        for item in current:
            if item["included"] and item["direction"] == "expense":
                entry = category_totals.setdefault(str(item["category"]), {"total": 0, "count": 0})
                entry["total"] += int(item["amount_cents"])
                entry["count"] += 1
        budgets = self._budgets()
        category_names = set(category_totals) | ({*budgets} - {"total"})
        categories = [
            {
                "id": name,
                "name": CATEGORIES[name],
                "total": _money(category_totals.get(name, {}).get("total", 0)),
                "count": category_totals.get(name, {}).get("count", 0),
                "share": (
                    round(category_totals.get(name, {}).get("total", 0) / spent * 100, 1)
                    if spent
                    else 0
                ),
            }
            for name in category_names
        ]
        for category in categories:
            limit = int(budgets.get(str(category["id"]), {}).get("limit_cents", 0))
            used = int(Decimal(str(category["total"])) * 100)
            category.update(
                {
                    "budget": _money(limit),
                    "budget_configured": bool(limit),
                    "budget_remaining": _money(max(0, limit - used)),
                    "budget_used_percent": round(used / limit * 100, 1) if limit else None,
                    "budget_status": (
                        "over"
                        if limit and used > limit
                        else "warning"
                        if limit and used >= limit * 0.8
                        else "ok"
                    ),
                }
            )
        categories.sort(key=lambda item: Decimal(str(item["total"])), reverse=True)
        current.sort(key=lambda item: str(item["occurred_at"]), reverse=True)
        coverage = self.mail_store.archive_coverage()
        coverage_dates = [
            _received(item["first_message"])
            for item in coverage
            if item.get("messages") and item.get("first_message")
        ]
        previous_complete = bool(coverage_dates) and min(coverage_dates) <= previous
        account_status = [
            {
                **item,
                "syncing": bool(
                    next(
                        (
                            self.mail_store.sync_progress(account["id"])
                            for account in self.mail_store.accounts()
                            if account["email"] == item["email"]
                        ),
                        None,
                    )
                ),
            }
            for item in coverage
        ]
        difference = spent - prior_spent
        today = datetime.now(TZ)
        days_total = calendar.monthrange(start.year, start.month)[1]
        if start <= today < end:
            days_elapsed = max(1, today.day)
            projected = int(round(spent / days_elapsed * days_total))
        elif today >= end:
            days_elapsed, projected = days_total, spent
        else:
            days_elapsed, projected = 0, 0
        configured_total = int(budgets.get("total", {}).get("limit_cents", 0))
        category_budget_total = sum(
            int(item.get("limit_cents", 0)) for key, item in budgets.items() if key != "total"
        )
        budget_limit = configured_total or category_budget_total
        profile = self.store.get(
            "finance_profile", "default", {"monthly_income_cents": 0, "savings_goal_cents": 0}
        )
        monthly_income = int(profile.get("monthly_income_cents", 0))
        savings_goal = int(profile.get("savings_goal_cents", 0))
        projected_savings = max(0, monthly_income - projected) if monthly_income else 0
        monthly_history = []
        for offset in range(-5, 1):
            item_start = _shift_month(start, offset)
            item_end = _shift_month(item_start, 1)
            item_total = total(
                [
                    item
                    for item in transactions
                    if item_start <= datetime.fromisoformat(str(item["occurred_at"])) < item_end
                ]
            )
            monthly_history.append(
                {
                    "month": item_start.strftime("%Y-%m"),
                    "total": _money(item_total),
                    "selected": item_start == start,
                }
            )
        merchant_totals: dict[str, dict[str, object]] = {}
        for item in current:
            if item["included"] and item["direction"] == "expense":
                key = str(item["merchant"]).casefold()
                record = merchant_totals.setdefault(
                    key, {"merchant": item["merchant"], "total_cents": 0, "count": 0}
                )
                record["total_cents"] = int(record["total_cents"]) + int(item["amount_cents"])
                record["count"] = int(record["count"]) + 1
        merchants = sorted(
            (
                {
                    "merchant": item["merchant"],
                    "total": _money(int(item["total_cents"])),
                    "count": item["count"],
                }
                for item in merchant_totals.values()
            ),
            key=lambda item: Decimal(str(item["total"])),
            reverse=True,
        )[:15]
        return {
            "month": start.strftime("%Y-%m"),
            "currency": "USD",
            "total_spent": _money(spent),
            "purchases": _money(total(current, kind="purchase")),
            "transfers": _money(total(current, kind="transfer")),
            "withdrawals": _money(total(current, kind="withdrawal")),
            "income": _money(total(current, direction="income")),
            "transaction_count": sum(
                1 for item in current if item["included"] and item["direction"] == "expense"
            ),
            "review_count": sum(1 for item in current if item["needs_review"]) + current_unparsed,
            "unparsed_count": current_unparsed,
            "categories": categories,
            "merchants": merchants,
            "transactions": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"amount_cents", "merchant_raw", "merchant_key"}
                }
                for item in current[:200]
            ],
            "comparison": {
                "previous_month": previous.strftime("%Y-%m"),
                "previous_total": _money(prior_spent),
                "difference": _money(abs(difference)),
                "direction": "up" if difference > 0 else "down" if difference < 0 else "equal",
                "percent": (round(abs(difference) / prior_spent * 100, 1) if prior_spent else None),
                "available": bool(prior) and previous_complete,
                "partial": bool(prior) and not previous_complete,
            },
            "history": monthly_history,
            "projection": {
                "amount": _money(projected),
                "days_elapsed": days_elapsed,
                "days_total": days_total,
                "status": (
                    "over"
                    if budget_limit and projected > budget_limit
                    else "warning"
                    if budget_limit and projected >= budget_limit * 0.9
                    else "ok"
                ),
            },
            "budget": {
                "limit": _money(budget_limit),
                "configured": bool(budget_limit),
                "source": "total" if configured_total else "categories",
                "spent": _money(spent),
                "remaining": _money(max(0, budget_limit - spent)),
                "used_percent": round(spent / budget_limit * 100, 1) if budget_limit else None,
            },
            "profile": {
                "monthly_income": _money(monthly_income),
                "savings_goal": _money(savings_goal),
                "projected_savings": _money(projected_savings),
                "savings_gap": _money(max(0, savings_goal - projected_savings)),
                "configured": bool(monthly_income or savings_goal),
                "goal_progress": (
                    round(projected_savings / savings_goal * 100, 1) if savings_goal else None
                ),
            },
            "recurring": self._recurring(transactions),
            "alerts": self._alerts(current, older),
            "accounts": account_status,
            "category_options": [
                {"id": identifier, "name": label} for identifier, label in CATEGORIES.items()
            ],
            "disclaimer": (
                "Estimación basada únicamente en notificaciones bancarias reconocidas. "
                "Compárala con tus estados de cuenta."
            ),
        }

    def set_budget(self, category: str, monthly_limit: object):
        if category not in {*CATEGORIES, "total"}:
            raise MailError("La categoría de presupuesto no es válida")
        limit = _setting_cents(monthly_limit, field="El presupuesto")
        if limit == 0:
            self.store.delete("finance_budget", category)
            return {"updated": True, "category": category, "removed": True}
        value = {
            "category": category,
            "limit_cents": limit,
            "monthly_limit": _money(limit),
            "updated": datetime.now(UTC).timestamp(),
        }
        self.store.put("finance_budget", category, value)
        return {"updated": True, **value}

    def set_profile(self, *, monthly_income: object, savings_goal: object):
        income = _setting_cents(monthly_income, field="El ingreso mensual")
        goal = _setting_cents(savings_goal, field="La meta de ahorro")
        if goal > income and income:
            raise MailError("La meta de ahorro no puede superar el ingreso mensual")
        value = {
            "monthly_income_cents": income,
            "savings_goal_cents": goal,
            "monthly_income": _money(income),
            "savings_goal": _money(goal),
            "updated": datetime.now(UTC).timestamp(),
        }
        self.store.put("finance_profile", "default", value)
        return {"updated": True, **value}

    def csv_export(self, month: str | None = None) -> tuple[str, bytes]:
        start, end, _previous = _month_bounds(month)
        transactions, _unparsed = self._transactions(start, end)
        transactions.sort(key=lambda item: str(item["occurred_at"]))
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "Fecha",
                "Banco",
                "Tipo",
                "Comercio",
                "Descripción",
                "Categoría",
                "Monto USD",
                "Dirección",
                "Incluido",
            ]
        )
        for item in transactions:
            writer.writerow(
                [
                    item["occurred_at"],
                    item["bank"],
                    item["kind"],
                    item["merchant"],
                    item["description"],
                    item["category_label"],
                    item["amount"],
                    item["direction"],
                    "sí" if item["included"] else "no",
                ]
            )
        name = f"jarvis-finanzas-{start:%Y-%m}.csv"
        return name, ("\ufeff" + output.getvalue()).encode("utf-8")

    def update(
        self,
        identifier: str,
        *,
        version: str,
        category: str,
        included: bool,
        merchant: str | None = None,
        remember_merchant: bool = False,
    ):
        if category not in CATEGORIES:
            raise MailError("La categoría seleccionada no es válida")
        rows = self.mail_store.archived_messages(limit=10_000)
        source = next((row for row in rows if row["id"] == identifier), None)
        transaction = _transaction(source) if source else None
        if not transaction:
            raise MailError("El movimiento ya no está disponible")
        if transaction["version"] != version:
            raise MailError("El correo cambió; actualiza la vista antes de editar")
        corrected_merchant = _compact(merchant)[:100] if merchant is not None else ""
        if merchant is not None and not corrected_merchant:
            raise MailError("El nombre del comercio no puede quedar vacío")
        if remember_merchant and corrected_merchant:
            self.store.put(
                "finance_merchant_alias",
                str(transaction["merchant_key"]),
                {
                    "merchant": corrected_merchant,
                    "updated": datetime.now(UTC).timestamp(),
                },
            )
        self.store.put(
            "finance_override",
            identifier,
            {
                "version": version,
                "category": category,
                "included": included,
                "merchant": corrected_merchant or transaction["merchant"],
                "updated": datetime.now(UTC).timestamp(),
            },
        )
        return {"updated": True, "id": identifier}

    def answer(self, query: str) -> str:
        normalized = _normalized(query)
        now = datetime.now(TZ)
        if "semana" in normalized:
            start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            transactions, _unparsed = self._transactions(start, now + timedelta(seconds=1))
            expenses = [
                item for item in transactions if item["included"] and item["direction"] == "expense"
            ]
            spent = sum(int(item["amount_cents"]) for item in expenses)
            return (
                f"Según las notificaciones bancarias, llevas ${_money(spent)} "
                f"en {len(expenses)} movimientos desde el lunes."
            )
        month = None
        if "mes pasado" in normalized:
            year = now.year - int(now.month == 1)
            number = 12 if now.month == 1 else now.month - 1
            month = f"{year:04d}-{number:02d}"
        else:
            for name, number in _MONTHS.items():
                if re.search(rf"\b{name}\b", normalized):
                    year_match = re.search(r"\b(20\d{2})\b", normalized)
                    year = int(year_match[1]) if year_match else now.year
                    month = f"{year:04d}-{number:02d}"
                    break
        data = self.summary(month)
        if "suscrip" in normalized or "recurrent" in normalized:
            recurring = data["recurring"]
            if not recurring:
                return "Todavía no tengo historial suficiente para detectar gastos recurrentes."
            leading = ", ".join(
                f"{item['merchant']} por unos ${item['monthly_estimate']}" for item in recurring[:4]
            )
            return "Detecté estos posibles pagos recurrentes: " + leading + "."
        if "proye" in normalized:
            return (
                f"Al ritmo actual, la proyección de gasto para {data['month']} es "
                f"${data['projection']['amount']}."
            )
        if "presupuesto" in normalized:
            if not data["budget"]["configured"]:
                return "Todavía no configuraste un presupuesto mensual en Mi día, Finanzas."
            return (
                f"Has usado ${data['budget']['spent']} de un presupuesto de "
                f"${data['budget']['limit']}; quedan ${data['budget']['remaining']}."
            )
        if "transfer" in normalized:
            return (
                f"Detecté ${data['transfers']} en transferencias durante {data['month']}. "
                "Puedes revisar o excluir transferencias propias en Mi día, Finanzas."
            )
        if "retiro" in normalized or "efectivo" in normalized:
            return f"Detecté ${data['withdrawals']} en retiros durante {data['month']}."
        if "ingres" in normalized:
            return f"Detecté ${data['income']} en ingresos bancarios durante {data['month']}."
        if data["transaction_count"] == 0:
            return (
                f"No detecté gastos confirmados en los correos de {data['month']}. "
                "Esto no sustituye el estado de cuenta."
            )
        leading = ", ".join(f"{item['name']} ${item['total']}" for item in data["categories"][:3])
        result = (
            f"Según las notificaciones bancarias, llevas ${data['total_spent']} "
            f"en {data['transaction_count']} movimientos durante {data['month']}."
        )
        if leading:
            result += " Las categorías principales son: " + leading + "."
        if data["review_count"]:
            result += f" Hay {data['review_count']} movimientos por revisar."
        return result


def finance_query(value: str) -> bool:
    normalized = _normalized(value)
    return bool(
        re.search(
            r"\b(?:gaste|gastado|gastando|gastos|finanzas|presupuesto|dinero|"
            r"transferi|transferencias|retiros?|ingresos?|suscripciones?|recurrentes?|"
            r"proyeccion|ahorro)\b",
            normalized,
        )
        and re.search(
            r"\b(?:cuanto|mes|semana|dinero|gaste|gastado|gastos|finanzas|en que|"
            r"presupuesto|suscripciones?|recurrentes?|proyeccion|ahorro)\b",
            normalized,
        )
    )

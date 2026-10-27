from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from jarvis.config import Settings
from jarvis.main import create_app
from jarvis.services.mail import MailService
from jarvis.services.organizer import Organizer


@pytest.fixture
def finance(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "jarvis.services.mail_store.protect",
        lambda value, decrypt=False: (
            base64.b64decode(value) if decrypt else base64.b64encode(value)
        ),
    )
    settings = Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        action_model_planning=False,
        appa_auto_discover=False,
        voice_preload=False,
    )
    mail = MailService(settings, None)
    account = mail.store.connect(
        "google",
        "owner@example.com",
        {
            "access_token": "test",
            "refresh_token": "test",
            "expires_at": time.time() + 3600,
            "client": {"client_id": "fixture"},
        },
    )
    organizer = Organizer(settings, mail, None)
    return organizer.finance, mail, account


def add(mail, account, version, subject, body, *, sender="bancaenlinea@produbanco.com"):
    mail.store.ingest(
        account,
        {
            "thread_id": "thread-" + version,
            "version": version,
            "subject": subject,
            "sender": sender,
            "received": "2026-10-20T15:00:00+00:00",
            "body": body,
            "url": "https://mail.google.com/mail/#all/" + version,
            "message_id": "<" + version + "@example.com>",
        },
    )


def add_purchase(mail, account, version, day, month, amount, merchant):
    add(
        mail,
        account,
        version,
        f"Consumo tarjeta de débito por USD {amount}",
        f"Fecha y Hora: {day:02d}/{month:02d}/2026 10:00 "
        "Transacción: Consumo Tarjeta de Débito Produbanco Detalle "
        f"Valor: USD {amount} Establecimiento: {merchant} "
        "Cuenta Débito: XXXXXX12345 Atentamente Produbanco",
    )


def test_finance_extracts_known_movements_and_ignores_promotions(finance):
    tracker, mail, account = finance
    add(
        mail,
        account,
        "purchase",
        "Consumo tarjeta de débito por USD 12.34",
        "Fecha y Hora: 20/Octubre/2026 10:00 Transacción: Consumo Tarjeta de Débito "
        "Produbanco Detalle Valor: USD 12.34 Establecimiento: KFC QUITO EC "
        "Cuenta Débito: ANA XXXXXX12345 Atentamente Produbanco",
    )
    add(
        mail,
        account,
        "transfer",
        "Transferencia enviada por $20.00",
        "Fecha y Hora: 20/10/2026 09:30:00 Transacción: Transferencia Acreditada "
        "Produbanco Detalle Beneficiario: Persona Uno Banco Beneficiario: Produbanco "
        "Cuenta Beneficiario: XXXXXX12345 Monto: $20.00 Descripción: Almuerzo "
        "Canal: App Móvil Referencia: 12345",
    )
    add(
        mail,
        account,
        "withdrawal",
        "Retiro de Efectivo Produbanco en Cajero Automático",
        "Fecha y Hora de Proceso: 19/10/2026 11:00 Transacción: Retiro de Efectivo "
        "Produbanco en Cajero Automático Detalle Monto: $10.00 Cuenta débito: ANA "
        "XXXXXX12345 Cajero: Produbanco Centro Si no realizaste esta transacción",
    )
    add(
        mail,
        account,
        "pichincha",
        "NOTIFICACION BANCO PICHINCHA",
        "TRANSFERENCIA Pago realizado correctamente Detalle Cuenta de origen: ******1234 "
        "Banco destino: DE UNA Cuenta acreditada: ******9999 Fecha: 18/10/2026 "
        "Nombre del beneficiario: Comercio Dos Identificación beneficiario: 1234567890 "
        "Monto: USD 5.25 Descripción: Número de documento: 12345",
        sender="Banco Pichincha <banco@pichincha.com>",
    )
    add(
        mail,
        account,
        "promo",
        "30% OFF en Rappi",
        "Válido en compras desde $30 y tope de descuento de $12 con tarjetas Produbanco.",
    )

    result = tracker.summary("2026-10")
    assert result["total_spent"] == "47.59"
    assert result["purchases"] == "12.34"
    assert result["transfers"] == "25.25"
    assert result["withdrawals"] == "10.00"
    assert result["transaction_count"] == 4
    assert len(result["transactions"]) == 4
    assert result["review_count"] == 2
    assert result["categories"][0]["name"] == "Transferencias"
    pichincha = next(item for item in result["transactions"] if item["bank"] == "Banco Pichincha")
    assert pichincha["merchant"] == "Comercio Dos"


def test_finance_archive_preserves_each_message_in_the_same_gmail_thread(finance):
    tracker, mail, account = finance
    for version, day, amount in (("one", 10, "3.00"), ("two", 11, "4.00")):
        mail.store.ingest(
            account,
            {
                "thread_id": "shared-bank-thread",
                "version": version,
                "subject": "Consumo tarjeta de débito",
                "sender": "Produbanco <bancaenlinea@produbanco.com>",
                "received": f"2026-10-{day:02d}T15:00:00+00:00",
                "body": f"Fecha y Hora: {day}/10/2026 10:00 Transacción: Consumo Tarjeta "
                f"de Débito Produbanco Detalle Valor: USD {amount} Establecimiento: TIENDA "
                "Cuenta Débito: XXXXXX12345",
                "url": "https://mail.google.com/mail/#all/shared-bank-thread",
            },
        )
    assert len(mail.store.list(True)) == 1
    assert len(mail.store.archived_messages()) == 2
    assert tracker.summary("2026-10")["total_spent"] == "7.00"


def test_finance_review_can_exclude_and_recategorize_without_changing_mail(finance):
    tracker, mail, account = finance
    add(
        mail,
        account,
        "transfer",
        "Transferencia enviada por $9.50",
        "Fecha y Hora: 20/10/2026 09:30 Transacción: Transferencia Acreditada Produbanco "
        "Beneficiario: Cuenta propia Banco Beneficiario: Produbanco Cuenta Beneficiario: "
        "XXXXXX12345 Monto: $9.50 Descripción: Ahorro Canal: App Móvil Referencia: 123",
    )
    transaction = tracker.summary("2026-10")["transactions"][0]
    tracker.update(
        transaction["id"],
        version=transaction["version"],
        category="otros",
        included=False,
    )
    updated = tracker.summary("2026-10")
    assert updated["total_spent"] == "0.00"
    assert updated["transactions"][0]["included"] is False
    assert updated["transactions"][0]["reviewed"] is True
    assert mail.store.get(mail.store.list(True)[0]["id"])["body"]


def test_finance_api_and_chat_query(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "jarvis.services.mail_store.protect",
        lambda value, decrypt=False: (
            base64.b64decode(value) if decrypt else base64.b64encode(value)
        ),
    )
    config = Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        action_model_planning=False,
        appa_auto_discover=False,
        voice_preload=False,
        safe_actions_enabled=False,
    )
    app = create_app(config)
    account = app.state.mail.store.connect("google", "owner@example.com", {})
    add(
        app.state.mail,
        account,
        "purchase",
        "Consumo tarjeta de débito por USD 7.25",
        "Fecha y Hora: 20/Octubre/2026 10:00 Transacción: Consumo Tarjeta de Débito "
        "Produbanco Detalle Valor: USD 7.25 Establecimiento: KFC Cuenta Débito: XXXXXX1",
    )
    with TestClient(app) as client:
        response = client.get("/api/organizer/finance?month=2026-10")
        assert response.status_code == 200 and response.json()["total_spent"] == "7.25"
        chat = client.post(
            "/api/chat", json={"message": "¿Cuánto he gastado en octubre de 2026?"}
        ).json()
        assert chat["provider"] == "local-finance" and "$7.25" in chat["response"]
        assert client.get("/api/organizer/finance?month=octubre").status_code == 400


def test_finance_20_budgets_profile_history_and_csv(finance):
    tracker, mail, account = finance
    add_purchase(mail, account, "food", 20, 10, "40.00", "KFC QUITO EC")
    add_purchase(mail, account, "prior", 20, 9, "25.00", "KFC QUITO EC")

    assert tracker.set_budget("total", "200.00")["monthly_limit"] == "200.00"
    assert tracker.set_budget("alimentacion", "60")["monthly_limit"] == "60.00"
    profile = tracker.set_profile(monthly_income="500", savings_goal="100")
    assert profile["monthly_income"] == "500.00"

    result = tracker.summary("2026-10")
    assert result["budget"] == {
        "limit": "200.00",
        "configured": True,
        "source": "total",
        "spent": "40.00",
        "remaining": "160.00",
        "used_percent": 20.0,
    }
    food = next(item for item in result["categories"] if item["id"] == "alimentacion")
    assert food["budget"] == "60.00" and food["budget_remaining"] == "20.00"
    assert result["history"][-2]["total"] == "25.00"
    assert result["history"][-1]["total"] == "40.00"
    assert result["profile"]["monthly_income"] == "500.00"
    assert float(result["projection"]["amount"]) >= 40

    name, content = tracker.csv_export("2026-10")
    decoded = content.decode("utf-8-sig")
    assert name == "jarvis-finanzas-2026-10.csv"
    assert "Fecha,Banco,Tipo,Comercio" in decoded
    assert "KFC" in decoded and "40.00" in decoded


def test_finance_20_detects_recurring_anomaly_and_remembers_merchant(finance):
    tracker, mail, account = finance
    for version, month in (("spotify-aug", 8), ("spotify-sep", 9), ("spotify-oct", 10)):
        add_purchase(mail, account, version, 10, month, "9.99", "SPOTIFY QUITO EC")
    for version, month in (("amazon-may", 5), ("amazon-jun", 6), ("amazon-jul", 7)):
        add_purchase(mail, account, version, 12, month, "10.00", "AMAZON QUITO EC")
    add_purchase(mail, account, "amazon-oct", 12, 10, "100.00", "AMAZON QUITO EC")
    add_purchase(
        mail,
        account,
        "coffee-one",
        13,
        10,
        "4.00",
        "PAYPHONE * CAFETERIA QUITO EC",
    )
    add_purchase(
        mail,
        account,
        "coffee-two",
        14,
        10,
        "5.00",
        "PAYPHONE * CAFETERIA QUITO EC",
    )

    first = next(
        item for item in tracker.summary("2026-10")["transactions"] if item["amount"] == "4.00"
    )
    tracker.update(
        first["id"],
        version=first["version"],
        category="alimentacion",
        included=True,
        merchant="Cafetería Central",
        remember_merchant=True,
    )
    result = tracker.summary("2026-10")
    coffees = [item for item in result["transactions"] if item["amount"] in {"4.00", "5.00"}]
    assert {item["merchant"] for item in coffees} == {"Cafetería Central"}
    spotify = next(item for item in result["recurring"] if item["merchant"] == "Spotify")
    assert spotify["monthly_estimate"] == "9.99" and spotify["confidence"] == "high"
    amazon = next(item for item in result["alerts"] if item["merchant"] == "Amazon")
    assert amazon["amount"] == "100.00" and amazon["baseline"] == "10.00"


def test_finance_20_api_configuration_query_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "jarvis.services.mail_store.protect",
        lambda value, decrypt=False: (
            base64.b64decode(value) if decrypt else base64.b64encode(value)
        ),
    )
    config = Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        action_model_planning=False,
        appa_auto_discover=False,
        voice_preload=False,
    )
    app = create_app(config)
    account = app.state.mail.store.connect("google", "owner@example.com", {})
    add_purchase(app.state.mail, account, "finance-api", 20, 10, "7.25", "KFC")
    with TestClient(app) as client:
        budget = client.put(
            "/api/organizer/finance/budget",
            json={"category": "total", "monthly_limit": "100"},
        )
        assert budget.status_code == 200 and budget.json()["monthly_limit"] == "100.00"
        assert (
            client.put(
                "/api/organizer/finance/profile",
                json={"monthly_income": "500", "savings_goal": "100"},
            ).status_code
            == 200
        )
        queried = client.post("/api/organizer/finance/query", json={"month": "2026-10"})
        assert queried.status_code == 200 and queried.json()["budget"]["limit"] == "100.00"
        exported = client.get("/api/organizer/finance/export.csv?month=2026-10")
        assert exported.status_code == 200
        assert exported.content.startswith(b"\xef\xbb\xbf")
        assert "jarvis-finanzas-2026-10.csv" in exported.headers["content-disposition"]
        invalid = client.put(
            "/api/organizer/finance/profile",
            json={"monthly_income": "50", "savings_goal": "100"},
        )
        assert invalid.status_code == 400

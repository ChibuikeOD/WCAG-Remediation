"""Billing API tests for Stripe checkout and invoice/PO requests."""

from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import backend.database as database
import backend.main as main_module
import backend.payments as payments_module
from backend.auth import require_user
from backend.config import settings
from backend.main import app


class FakeCheckoutSession:
    created = []

    @staticmethod
    def create(**kwargs):
        FakeCheckoutSession.created.append(kwargs)
        return SimpleNamespace(id="cs_test_123", url="https://checkout.stripe.test/pay")


class FakeWebhook:
    event = None

    @staticmethod
    def construct_event(payload, sig_header, secret):
        return FakeWebhook.event


class FakeStripe:
    api_key = None
    api_version = None
    checkout = SimpleNamespace(Session=FakeCheckoutSession)
    Webhook = FakeWebhook


def paid_checkout_event():
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "mode": "payment",
                "payment_status": "paid",
                "payment_intent": "pi_test_123",
                "customer": "cus_test_123",
            }
        },
    }


def paid_invoice_event(purchase_id):
    return {
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_test_123",
                "status": "paid",
                "payment_intent": "pi_invoice_123",
                "customer": "cus_invoice_123",
                "metadata": {"purchase_id": purchase_id},
            }
        },
    }


def subscription_checkout_event():
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "mode": "subscription",
                "payment_status": "paid",
                "subscription": "sub_test_123",
                "customer": "cus_sub_123",
            }
        },
    }


def paid_subscription_invoice_event():
    return {
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_sub_123",
                "status": "paid",
                "payment_intent": "pi_sub_123",
                "customer": "cus_sub_123",
                "subscription": "sub_test_123",
                "metadata": {},
            }
        },
    }


def make_client(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'billing.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    database.Base.metadata.create_all(test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(payments_module, "SessionLocal", session_factory)
    monkeypatch.setattr(payments_module, "stripe", FakeStripe)
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "testing")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr("sk_test_123"))
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", SecretStr("whsec_123"))
    monkeypatch.setattr(settings, "STRIPE_REMEDIATION_COMMUNITY_PRICE_ID", "price_rem_community")
    monkeypatch.setattr(settings, "STRIPE_REMEDIATION_LIBRARY_PRICE_ID", "price_rem_library")
    monkeypatch.setattr(settings, "STRIPE_REMEDIATION_CAMPUS_PRICE_ID", "price_rem_campus")
    monkeypatch.setattr(settings, "STRIPE_AUDIT_COMMUNITY_PRICE_ID", "price_audit_community")
    monkeypatch.setattr(settings, "STRIPE_AUDIT_LIBRARY_PRICE_ID", "price_audit_library")
    monkeypatch.setattr(settings, "STRIPE_AUDIT_CAMPUS_PRICE_ID", "price_audit_campus")
    FakeCheckoutSession.created = []
    FakeWebhook.event = None
    client = TestClient(app, raise_server_exceptions=False)
    return client, session_factory, test_engine


def test_checkout_session_uses_server_catalog_and_records_pending_purchase(
    tmp_path, monkeypatch
):
    client, session_factory, test_engine = make_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/billing/checkout-session",
            json={"pack_key": "starter", "service_mode": "remediation"},
        )

        assert response.status_code == 200
        assert response.json()["checkout_session_id"] == "cs_test_123"
        assert response.json()["url"] == "https://checkout.stripe.test/pay"
        [line_item] = FakeCheckoutSession.created[0]["line_items"]
        assert line_item["price_data"]["unit_amount"] == 4900
        assert FakeCheckoutSession.created[0]["mode"] == "payment"
        with session_factory() as session:
            [purchase] = session.scalars(select(database.CreditPurchase)).all()
            assert purchase.status == "pending"
            assert purchase.pages_included == 250
            assert purchase.stripe_checkout_session_id == "cs_test_123"
    finally:
        client.close()
        test_engine.dispose()


def test_checkout_webhook_fulfills_paid_session_once(tmp_path, monkeypatch):
    client, session_factory, test_engine = make_client(tmp_path, monkeypatch)
    try:
        assert client.post(
            "/billing/checkout-session",
            json={"pack_key": "starter", "service_mode": "remediation"},
        ).status_code == 200
        FakeWebhook.event = paid_checkout_event()

        first = client.post(
            "/billing/webhook",
            data=b"{}",
            headers={"Stripe-Signature": "valid-signature"},
        )
        duplicate = client.post(
            "/billing/webhook",
            data=b"{}",
            headers={"Stripe-Signature": "valid-signature"},
        )

        assert first.status_code == duplicate.status_code == 200
        with session_factory() as session:
            [purchase] = session.scalars(select(database.CreditPurchase)).all()
            entries = session.scalars(select(database.TrialLedgerEntry)).all()
            assert purchase.status == "fulfilled"
            assert purchase.expires_at is not None
            assert [entry.entry_type for entry in entries] == ["grant", "purchase"]
            assert sum(entry.granted_delta for entry in entries) == 650
    finally:
        client.close()
        test_engine.dispose()


def test_institutional_invoice_request_records_domain_verification(
    tmp_path, monkeypatch
):
    client, session_factory, test_engine = make_client(tmp_path, monkeypatch)
    with session_factory() as session:
        session.add(database.User(id="library-user", email="buyer@library.org", name="Buyer"))
        session.commit()

    def library_user():
        with session_factory() as session:
            return session.get(database.User, "library-user")

    app.dependency_overrides[require_user] = library_user
    try:
        response = client.post(
            "/billing/invoice-request",
            json={
                "plan_key": "library",
                "service_mode": "audit",
                "organization_name": "City Library",
                "contact_name": "Avery Buyer",
                "contact_email": "avery@library.org",
                "po_number": "PO-42",
            },
        )

        assert response.status_code == 200
        assert response.json()["domain_verified"] is True
        purchase_id = response.json()["purchase_id"]
        with session_factory() as session:
            [request_row] = session.scalars(
                select(database.InstitutionalInvoiceRequest)
            ).all()
            [purchase] = session.scalars(select(database.CreditPurchase)).all()
            assert request_row.plan_key == "library"
            assert request_row.service_mode == "audit"
            assert request_row.annual_price_cents == 44900
            assert request_row.overage_cents == 7
            assert request_row.status == "requested"
            assert purchase.id == purchase_id
            assert purchase.purchase_type == "institutional_plan"
            assert purchase.status == "invoice_requested"
            assert purchase.pages_included == 8000
    finally:
        app.dependency_overrides.clear()
        client.close()
        test_engine.dispose()


def test_subscription_checkout_uses_configured_price_and_records_pending_purchase(
    tmp_path, monkeypatch
):
    client, session_factory, test_engine = make_client(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/billing/subscription-checkout-session",
            json={"plan_key": "library", "service_mode": "audit"},
        )

        assert response.status_code == 200
        assert response.json()["checkout_session_id"] == "cs_test_123"
        [line_item] = FakeCheckoutSession.created[0]["line_items"]
        assert FakeCheckoutSession.created[0]["mode"] == "subscription"
        assert line_item == {"price": "price_audit_library", "quantity": 1}
        assert FakeCheckoutSession.created[0]["subscription_data"]["metadata"][
            "purchase_type"
        ] == "subscription_plan"
        with session_factory() as session:
            [purchase] = session.scalars(select(database.CreditPurchase)).all()
            assert purchase.purchase_type == "subscription_plan"
            assert purchase.catalog_key == "library"
            assert purchase.service_mode == "audit"
            assert purchase.status == "pending"
            assert purchase.pages_included == 8000
            assert purchase.stripe_checkout_session_id == "cs_test_123"
    finally:
        client.close()
        test_engine.dispose()


def test_subscription_invoice_webhook_grants_recurring_pages_once(
    tmp_path, monkeypatch
):
    client, session_factory, test_engine = make_client(tmp_path, monkeypatch)
    try:
        checkout = client.post(
            "/billing/subscription-checkout-session",
            json={"plan_key": "community", "service_mode": "remediation"},
        )
        assert checkout.status_code == 200
        FakeWebhook.event = subscription_checkout_event()
        checkout_webhook = client.post(
            "/billing/webhook",
            data=b"{}",
            headers={"Stripe-Signature": "valid-signature"},
        )
        assert checkout_webhook.status_code == 200

        FakeWebhook.event = paid_subscription_invoice_event()
        first_invoice = client.post(
            "/billing/webhook",
            data=b"{}",
            headers={"Stripe-Signature": "valid-signature"},
        )
        duplicate_invoice = client.post(
            "/billing/webhook",
            data=b"{}",
            headers={"Stripe-Signature": "valid-signature"},
        )

        assert first_invoice.status_code == duplicate_invoice.status_code == 200
        with session_factory() as session:
            [purchase] = session.scalars(select(database.CreditPurchase)).all()
            entries = session.scalars(select(database.TrialLedgerEntry)).all()
            assert purchase.status == "active"
            assert purchase.stripe_subscription_id == "sub_test_123"
            assert purchase.stripe_customer_id == "cus_sub_123"
            assert [entry.entry_type for entry in entries] == ["grant", "purchase"]
            assert sum(entry.granted_delta for entry in entries) == 2900
    finally:
        client.close()
        test_engine.dispose()


def test_paid_invoice_webhook_fulfills_institutional_purchase(tmp_path, monkeypatch):
    client, session_factory, test_engine = make_client(tmp_path, monkeypatch)
    with session_factory() as session:
        session.add(database.User(id="library-user", email="buyer@library.org", name="Buyer"))
        session.commit()

    def library_user():
        with session_factory() as session:
            return session.get(database.User, "library-user")

    app.dependency_overrides[require_user] = library_user
    try:
        invoice_request = client.post(
            "/billing/invoice-request",
            json={
                "plan_key": "community",
                "service_mode": "remediation",
                "organization_name": "City Library",
                "contact_name": "Avery Buyer",
                "contact_email": "avery@library.org",
            },
        )
        assert invoice_request.status_code == 200
        FakeWebhook.event = paid_invoice_event(invoice_request.json()["purchase_id"])

        webhook = client.post(
            "/billing/webhook",
            data=b"{}",
            headers={"Stripe-Signature": "valid-signature"},
        )

        assert webhook.status_code == 200
        with session_factory() as session:
            [purchase] = session.scalars(select(database.CreditPurchase)).all()
            entries = session.scalars(select(database.TrialLedgerEntry)).all()
            assert purchase.status == "fulfilled"
            assert purchase.expires_at is not None
            assert [entry.entry_type for entry in entries] == ["grant", "purchase"]
            assert sum(entry.granted_delta for entry in entries) == 2900
    finally:
        app.dependency_overrides.clear()
        client.close()
        test_engine.dispose()

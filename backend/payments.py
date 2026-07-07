"""Stripe billing and institutional invoice request endpoints."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .auth import User, require_user
from .config import settings
from .database import (
    CreditPurchase,
    InstitutionalInvoiceRequest,
    SessionLocal,
    User as DbUser,
    get_db,
)
from .trial import TrialService, TrialStateError
from .trial.eligibility import classify_verified_email

try:
    import stripe
except ImportError:  # pragma: no cover - exercised only without dependencies installed
    stripe = None


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["Billing"])

ServiceMode = Literal["remediation", "audit"]

STRIPE_API_VERSION = "2026-02-25.clover"
CREDIT_EXPIRY_DAYS = 365

PAYG_PACKS: dict[str, dict[str, Any]] = {
    "starter": {
        "name": "Starter",
        "pages": 250,
        "amount_cents": 4900,
        "per_page_cents": 20,
        "notes": "Post-trial bump from 400 free",
    },
    "standard": {
        "name": "Standard",
        "pages": 1000,
        "amount_cents": 14900,
        "per_page_cents": 15,
        "notes": "Small library backlog",
    },
    "pro": {
        "name": "Pro",
        "pages": 5000,
        "amount_cents": 59900,
        "per_page_cents": 12,
        "notes": "Department-level",
    },
}

AUDIT_PACKS: dict[str, dict[str, Any]] = {
    "starter": {**PAYG_PACKS["starter"], "amount_cents": 2500, "per_page_cents": 10},
    "standard": {**PAYG_PACKS["standard"], "amount_cents": 7500, "per_page_cents": 8},
    "pro": {**PAYG_PACKS["pro"], "amount_cents": 30000, "per_page_cents": 6},
}

INSTITUTIONAL_PLANS: dict[str, dict[str, Any]] = {
    "community": {
        "name": "Community",
        "annual_price_cents": 39900,
        "pages": 2500,
        "overage_cents": 18,
        "best_for": "Small public library",
    },
    "library": {
        "name": "Library",
        "annual_price_cents": 89900,
        "pages": 8000,
        "overage_cents": 14,
        "best_for": "Mid-size system",
    },
    "campus": {
        "name": "Campus",
        "annual_price_cents": 249900,
        "pages": 30000,
        "overage_cents": 10,
        "best_for": "University, large district",
    },
}

AUDIT_INSTITUTIONAL_PLANS: dict[str, dict[str, Any]] = {
    "community": {
        **INSTITUTIONAL_PLANS["community"],
        "annual_price_cents": 19900,
        "overage_cents": 9,
    },
    "library": {
        **INSTITUTIONAL_PLANS["library"],
        "annual_price_cents": 44900,
        "overage_cents": 7,
    },
    "campus": {
        **INSTITUTIONAL_PLANS["campus"],
        "annual_price_cents": 124900,
        "overage_cents": 5,
    },
}


class CheckoutSessionRequest(BaseModel):
    pack_key: Literal["starter", "standard", "pro"]
    service_mode: ServiceMode = "remediation"


class SubscriptionCheckoutSessionRequest(BaseModel):
    plan_key: Literal["community", "library", "campus"]
    service_mode: ServiceMode = "remediation"


class CheckoutSessionResponse(BaseModel):
    purchase_id: str
    checkout_session_id: str
    url: str


class CheckoutSessionStatusResponse(BaseModel):
    status: str
    payment_status: str | None = None
    fulfilled: bool
    remaining_pages: int | None = None


class InvoiceRequestPayload(BaseModel):
    plan_key: Literal["community", "library", "campus"]
    service_mode: ServiceMode = "remediation"
    organization_name: str = Field(min_length=2, max_length=160)
    contact_name: str = Field(min_length=2, max_length=120)
    contact_email: str = Field(min_length=3, max_length=254)
    po_number: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str) -> str:
        classify_verified_email(value)
        return value.strip().lower()


class InvoiceRequestResponse(BaseModel):
    request_id: str
    purchase_id: str
    plan_key: str
    service_mode: ServiceMode
    domain_verified: bool
    status: str


def _service_catalog(service_mode: ServiceMode) -> tuple[dict[str, Any], dict[str, Any]]:
    if service_mode == "audit":
        return AUDIT_PACKS, AUDIT_INSTITUTIONAL_PLANS
    return PAYG_PACKS, INSTITUTIONAL_PLANS


def _stripe_secret() -> str:
    if stripe is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe SDK is not installed",
        )
    if settings.STRIPE_SECRET_KEY is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured",
        )
    secret = settings.STRIPE_SECRET_KEY.get_secret_value()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured",
        )
    stripe.api_key = secret
    stripe.api_version = STRIPE_API_VERSION
    return secret


def _stripe_webhook_secret() -> str:
    if settings.STRIPE_WEBHOOK_SECRET is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook signing secret is not configured",
        )
    secret = settings.STRIPE_WEBHOOK_SECRET.get_secret_value()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook signing secret is not configured",
        )
    return secret


def _stripe_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalized_email_domain(email: str) -> str:
    return classify_verified_email(email).normalized_domain


def _is_verified_institutional_domain(domain: str) -> bool:
    return domain.endswith(".edu") or domain.endswith(".org") or domain.endswith(".gov")


def _purchase_metadata(purchase: CreditPurchase) -> dict[str, str]:
    return {
        "purchase_id": purchase.id,
        "user_id": purchase.user_id,
        "purchase_type": purchase.purchase_type,
        "catalog_key": purchase.catalog_key,
        "service_mode": purchase.service_mode,
        "pages_included": str(purchase.pages_included),
    }


def _catalog_pack(pack_key: str, service_mode: ServiceMode) -> dict[str, Any]:
    packs, _ = _service_catalog(service_mode)
    return packs[pack_key]


def _catalog_plan(plan_key: str, service_mode: ServiceMode) -> dict[str, Any]:
    _, plans = _service_catalog(service_mode)
    return plans[plan_key]


def _subscription_price_id(plan_key: str, service_mode: ServiceMode) -> str:
    env_name = f"STRIPE_{service_mode.upper()}_{plan_key.upper()}_PRICE_ID"
    price_id = getattr(settings, env_name, None)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Stripe subscription price is not configured for {service_mode} {plan_key}",
        )
    return price_id


def _fulfill_purchase(
    db: Session,
    purchase: CreditPurchase,
    *,
    idempotency_key: str,
    stripe_payment_intent_id: str | None,
    stripe_customer_id: str | None,
) -> int | None:
    if purchase.status == "fulfilled":
        return None

    user = db.get(DbUser, purchase.user_id)
    if user is None:
        raise TrialStateError("Purchase user does not exist")

    now = datetime.now(timezone.utc)
    purchase.stripe_payment_intent_id = stripe_payment_intent_id
    purchase.stripe_customer_id = stripe_customer_id
    purchase.expires_at = now + timedelta(days=CREDIT_EXPIRY_DAYS)
    purchase.fulfilled_at = now
    purchase.status = "fulfilled"

    service = TrialService(db)
    service.ensure_account(user)
    balance = service.grant_paid_pages(
        purchase.user_id,
        purchase.pages_included,
        idempotency_key,
    )
    return balance.remaining


def _fulfill_checkout_session(db: Session, checkout_session: Any) -> int | None:
    session_id = _stripe_value(checkout_session, "id")
    if not session_id:
        raise TrialStateError("Stripe checkout session is missing an id")
    purchase = (
        db.query(CreditPurchase)
        .filter(CreditPurchase.stripe_checkout_session_id == session_id)
        .first()
    )
    if purchase is None:
        metadata = _stripe_value(checkout_session, "metadata", {}) or {}
        purchase_id = metadata.get("purchase_id") if isinstance(metadata, dict) else None
        purchase = db.get(CreditPurchase, purchase_id) if purchase_id else None
    if purchase is None:
        raise TrialStateError("Stripe checkout session does not match a purchase")

    mode = _stripe_value(checkout_session, "mode")
    if mode == "subscription":
        return _activate_subscription_checkout(db, checkout_session, purchase)
    if mode != "payment":
        raise TrialStateError("Stripe checkout session has an unsupported mode")
    if _stripe_value(checkout_session, "payment_status") != "paid":
        return None

    return _fulfill_purchase(
        db,
        purchase,
        idempotency_key=f"stripe_checkout:{session_id}",
        stripe_payment_intent_id=_stripe_value(checkout_session, "payment_intent"),
        stripe_customer_id=_stripe_value(checkout_session, "customer"),
    )


def _activate_subscription_checkout(
    db: Session,
    checkout_session: Any,
    purchase: CreditPurchase,
) -> None:
    if purchase.purchase_type != "subscription_plan":
        raise TrialStateError("Stripe subscription session does not match a subscription purchase")
    subscription_id = _stripe_value(checkout_session, "subscription")
    if not subscription_id:
        raise TrialStateError("Stripe subscription checkout is missing a subscription id")
    purchase.stripe_subscription_id = subscription_id
    purchase.stripe_customer_id = _stripe_value(checkout_session, "customer")
    purchase.status = "active"
    db.commit()
    return None


def _fulfill_paid_invoice(db: Session, invoice: Any) -> int | None:
    subscription_id = _stripe_value(invoice, "subscription")
    if subscription_id:
        return _fulfill_subscription_invoice(db, invoice, subscription_id)

    invoice_id = _stripe_value(invoice, "id")
    if not invoice_id:
        raise TrialStateError("Stripe invoice is missing an id")
    metadata = _stripe_value(invoice, "metadata", {}) or {}
    purchase_id = metadata.get("purchase_id") if isinstance(metadata, dict) else None
    purchase = db.get(CreditPurchase, purchase_id) if purchase_id else None
    if purchase is None:
        raise TrialStateError("Stripe invoice does not match a purchase")
    if _stripe_value(invoice, "status") != "paid":
        return None
    return _fulfill_purchase(
        db,
        purchase,
        idempotency_key=f"stripe_invoice:{invoice_id}",
        stripe_payment_intent_id=_stripe_value(invoice, "payment_intent"),
        stripe_customer_id=_stripe_value(invoice, "customer"),
    )


def _fulfill_subscription_invoice(
    db: Session,
    invoice: Any,
    subscription_id: str,
) -> int | None:
    invoice_id = _stripe_value(invoice, "id")
    if not invoice_id:
        raise TrialStateError("Stripe invoice is missing an id")
    if _stripe_value(invoice, "status") != "paid":
        return None

    metadata = _stripe_value(invoice, "metadata", {}) or {}
    purchase_id = metadata.get("purchase_id") if isinstance(metadata, dict) else None
    purchase = db.get(CreditPurchase, purchase_id) if purchase_id else None
    if purchase is None:
        purchase = (
            db.query(CreditPurchase)
            .filter(CreditPurchase.stripe_subscription_id == subscription_id)
            .first()
        )
    if purchase is None or purchase.purchase_type != "subscription_plan":
        raise TrialStateError("Stripe invoice does not match a subscription purchase")

    user = db.get(DbUser, purchase.user_id)
    if user is None:
        raise TrialStateError("Purchase user does not exist")

    now = datetime.now(timezone.utc)
    purchase.stripe_payment_intent_id = _stripe_value(invoice, "payment_intent")
    purchase.stripe_customer_id = _stripe_value(invoice, "customer")
    purchase.stripe_subscription_id = subscription_id
    purchase.expires_at = now + timedelta(days=CREDIT_EXPIRY_DAYS)
    purchase.fulfilled_at = purchase.fulfilled_at or now
    purchase.status = "active"

    service = TrialService(db)
    service.ensure_account(user)
    balance = service.grant_paid_pages(
        purchase.user_id,
        purchase.pages_included,
        f"stripe_invoice:{invoice_id}",
    )
    return balance.remaining


@router.get("/catalog")
async def billing_catalog() -> dict[str, Any]:
    return {
        "currency": "usd",
        "credit_validity_months": 12,
        "service_modes": {
            "remediation": {
                "label": "Full remediation",
                "pay_as_you_go": PAYG_PACKS,
                "institutional_annual": INSTITUTIONAL_PLANS,
            },
            "audit": {
                "label": "Audit/report only",
                "pay_as_you_go": AUDIT_PACKS,
                "institutional_annual": AUDIT_INSTITUTIONAL_PLANS,
            },
        },
        "institutional_terms": {
            "shared_org_account": True,
            "domain_verification": [".edu", ".org", ".gov"],
            "invoice_and_po": True,
            "annual_true_up_at_renewal": True,
        },
    }


@router.post("/checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> CheckoutSessionResponse:
    _stripe_secret()
    pack = _catalog_pack(payload.pack_key, payload.service_mode)
    purchase = CreditPurchase(
        id=str(uuid4()),
        user_id=user.id,
        purchase_type="credit_pack",
        catalog_key=payload.pack_key,
        service_mode=payload.service_mode,
        pages_included=pack["pages"],
        amount_cents=pack["amount_cents"],
        currency="usd",
        status="pending",
        metadata_json=json.dumps({"source": "checkout"}),
    )
    db.add(purchase)
    db.flush()

    product_name = f"PDFAccess {pack['name']} {payload.service_mode} credits"
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="payment",
            success_url=settings.BILLING_SUCCESS_URL,
            cancel_url=settings.BILLING_CANCEL_URL,
            customer_email=user.email,
            client_reference_id=purchase.id,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": pack["amount_cents"],
                        "product_data": {
                            "name": product_name,
                            "description": f"{pack['pages']:,} pages, valid 12 months",
                            "metadata": _purchase_metadata(purchase),
                        },
                    },
                }
            ],
            metadata=_purchase_metadata(purchase),
            payment_intent_data={"metadata": _purchase_metadata(purchase)},
            allow_promotion_codes=True,
        )
    except Exception:
        db.rollback()
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create Stripe checkout session",
        ) from None

    purchase.stripe_checkout_session_id = checkout_session.id
    db.commit()
    return CheckoutSessionResponse(
        purchase_id=purchase.id,
        checkout_session_id=checkout_session.id,
        url=checkout_session.url,
    )


@router.post("/subscription-checkout-session", response_model=CheckoutSessionResponse)
async def create_subscription_checkout_session(
    payload: SubscriptionCheckoutSessionRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> CheckoutSessionResponse:
    _stripe_secret()
    plan = _catalog_plan(payload.plan_key, payload.service_mode)
    price_id = _subscription_price_id(payload.plan_key, payload.service_mode)
    purchase = CreditPurchase(
        id=str(uuid4()),
        user_id=user.id,
        purchase_type="subscription_plan",
        catalog_key=payload.plan_key,
        service_mode=payload.service_mode,
        pages_included=plan["pages"],
        amount_cents=plan["annual_price_cents"],
        currency="usd",
        status="pending",
        metadata_json=json.dumps({"source": "subscription_checkout"}),
    )
    db.add(purchase)
    db.flush()

    metadata = _purchase_metadata(purchase)
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            success_url=settings.BILLING_SUCCESS_URL,
            cancel_url=settings.BILLING_CANCEL_URL,
            customer_email=user.email,
            client_reference_id=purchase.id,
            line_items=[{"price": price_id, "quantity": 1}],
            metadata=metadata,
            subscription_data={"metadata": metadata},
            allow_promotion_codes=True,
        )
    except Exception:
        db.rollback()
        logger.exception("Stripe subscription checkout session creation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create Stripe subscription checkout session",
        ) from None

    purchase.stripe_checkout_session_id = checkout_session.id
    db.commit()
    return CheckoutSessionResponse(
        purchase_id=purchase.id,
        checkout_session_id=checkout_session.id,
        url=checkout_session.url,
    )


@router.get(
    "/checkout-session/{session_id}/status",
    response_model=CheckoutSessionStatusResponse,
)
async def checkout_session_status(
    session_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> CheckoutSessionStatusResponse:
    purchase = (
        db.query(CreditPurchase)
        .filter(
            CreditPurchase.user_id == user.id,
            CreditPurchase.stripe_checkout_session_id == session_id,
        )
        .first()
    )
    if purchase is None:
        raise HTTPException(status_code=404, detail="Checkout session not found")
    return CheckoutSessionStatusResponse(
        status=purchase.status,
        payment_status="paid" if purchase.status == "fulfilled" else None,
        fulfilled=purchase.status == "fulfilled",
    )


@router.post("/invoice-request", response_model=InvoiceRequestResponse)
async def request_institutional_invoice(
    payload: InvoiceRequestPayload,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> InvoiceRequestResponse:
    plan = _catalog_plan(payload.plan_key, payload.service_mode)
    normalized_domain = _normalized_email_domain(user.email)
    domain_verified = _is_verified_institutional_domain(normalized_domain)
    request_row = InstitutionalInvoiceRequest(
        id=str(uuid4()),
        user_id=user.id,
        plan_key=payload.plan_key,
        service_mode=payload.service_mode,
        organization_name=payload.organization_name.strip(),
        contact_name=payload.contact_name.strip(),
        contact_email=str(payload.contact_email).lower(),
        normalized_domain=normalized_domain,
        domain_verified=1 if domain_verified else 0,
        po_number=payload.po_number.strip() if payload.po_number else None,
        notes=payload.notes.strip() if payload.notes else None,
        pages_included=plan["pages"],
        annual_price_cents=plan["annual_price_cents"],
        overage_cents=plan["overage_cents"],
        status="requested",
    )
    purchase = CreditPurchase(
        id=str(uuid4()),
        user_id=user.id,
        purchase_type="institutional_plan",
        catalog_key=payload.plan_key,
        service_mode=payload.service_mode,
        pages_included=plan["pages"],
        amount_cents=plan["annual_price_cents"],
        currency="usd",
        status="invoice_requested",
        metadata_json=json.dumps({"invoice_request_id": request_row.id}),
    )
    db.add_all((request_row, purchase))
    db.commit()
    return InvoiceRequestResponse(
        request_id=request_row.id,
        purchase_id=purchase.id,
        plan_key=payload.plan_key,
        service_mode=payload.service_mode,
        domain_verified=domain_verified,
        status=request_row.status,
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, bool]:
    _stripe_secret()
    webhook_secret = _stripe_webhook_secret()
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=webhook_secret,
        )
    except Exception:
        logger.info("Rejected Stripe webhook with invalid signature")
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from None

    event_type = _stripe_value(event, "type")
    event_object = _stripe_value(_stripe_value(event, "data", {}), "object", {})
    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        db = SessionLocal()
        try:
            _fulfill_checkout_session(db, event_object)
        except TrialStateError:
            db.rollback()
            logger.exception("Stripe checkout fulfillment failed")
            raise HTTPException(
                status_code=409, detail="Stripe checkout fulfillment failed"
            ) from None
        finally:
            db.close()
    elif event_type == "invoice.paid":
        db = SessionLocal()
        try:
            _fulfill_paid_invoice(db, event_object)
        except TrialStateError:
            db.rollback()
            logger.exception("Stripe invoice fulfillment failed")
            raise HTTPException(
                status_code=409, detail="Stripe invoice fulfillment failed"
            ) from None
        finally:
            db.close()
    return {"received": True}

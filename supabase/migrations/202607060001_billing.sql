-- Stripe credit purchases and institutional invoice/PO requests.

alter table public.trial_ledger_entries
    drop constraint ck_trial_ledger_entry_type,
    drop constraint ck_trial_ledger_signed_deltas;

alter table public.trial_ledger_entries
    add constraint ck_trial_ledger_entry_type
        check (entry_type in ('grant', 'purchase', 'reserve', 'consume', 'release')),
    add constraint ck_trial_ledger_signed_deltas
        check (
            (entry_type = 'grant'
                and granted_delta > 0
                and reserved_delta = 0
                and consumed_delta = 0
                and job_id is null)
            or (entry_type = 'purchase'
                and granted_delta > 0
                and reserved_delta = 0
                and consumed_delta = 0
                and job_id is null)
            or (entry_type = 'reserve'
                and granted_delta = 0
                and reserved_delta > 0
                and consumed_delta = 0
                and job_id is not null)
            or (entry_type = 'release'
                and granted_delta = 0
                and reserved_delta < 0
                and consumed_delta = 0
                and job_id is not null)
            or (entry_type = 'consume'
                and granted_delta = 0
                and reserved_delta < 0
                and consumed_delta > 0
                and consumed_delta = -reserved_delta
                and job_id is not null)
        );

create table public.credit_purchases (
    id text primary key,
    user_id text not null references public.users(id) on delete cascade,
    purchase_type text not null,
    catalog_key text not null,
    service_mode text not null,
    pages_included integer not null,
    amount_cents integer not null,
    currency text not null default 'usd',
    status text not null,
    stripe_checkout_session_id text unique null,
    stripe_payment_intent_id text null,
    stripe_customer_id text null,
    stripe_subscription_id text unique null,
    expires_at timestamp with time zone null,
    metadata_json text null,
    created_at timestamp with time zone not null default now(),
    fulfilled_at timestamp with time zone null,
    constraint uq_credit_purchases_user_stripe_session
        unique (user_id, stripe_checkout_session_id),
    constraint ck_credit_purchases_type
        check (purchase_type in ('credit_pack', 'institutional_plan', 'subscription_plan')),
    constraint ck_credit_purchases_service_mode
        check (service_mode in ('remediation', 'audit')),
    constraint ck_credit_purchases_status
        check (status in ('pending', 'active', 'fulfilled', 'invoice_requested', 'invoice_sent', 'paid', 'past_due', 'canceled', 'void')),
    constraint ck_credit_purchases_pages_positive
        check (pages_included > 0),
    constraint ck_credit_purchases_amount_nonnegative
        check (amount_cents >= 0)
);

create index ix_credit_purchases_user_id
    on public.credit_purchases (user_id);
create index ix_credit_purchases_status
    on public.credit_purchases (status);
create index ix_credit_purchases_stripe_checkout_session_id
    on public.credit_purchases (stripe_checkout_session_id);
create index ix_credit_purchases_stripe_subscription_id
    on public.credit_purchases (stripe_subscription_id);

create table public.institutional_invoice_requests (
    id text primary key,
    user_id text not null references public.users(id) on delete cascade,
    plan_key text not null,
    service_mode text not null,
    organization_name text not null,
    contact_name text not null,
    contact_email text not null,
    normalized_domain text not null,
    domain_verified integer not null default 0,
    po_number text null,
    notes text null,
    pages_included integer not null,
    annual_price_cents integer not null,
    overage_cents integer not null,
    status text not null default 'requested',
    created_at timestamp with time zone not null default now(),
    constraint ck_invoice_requests_service_mode
        check (service_mode in ('remediation', 'audit')),
    constraint ck_invoice_requests_status
        check (status in ('requested', 'approved', 'invoice_sent', 'paid', 'declined')),
    constraint ck_invoice_requests_domain_verified
        check (domain_verified in (0, 1))
);

create index ix_invoice_requests_user_id
    on public.institutional_invoice_requests (user_id);
create index ix_invoice_requests_status
    on public.institutional_invoice_requests (status);

alter table public.credit_purchases enable row level security;
alter table public.institutional_invoice_requests enable row level security;

create policy "Users can view their own credit purchases"
on public.credit_purchases
for select
to authenticated
using (auth.uid()::text = user_id);

create policy "Users can view their own invoice requests"
on public.institutional_invoice_requests
for select
to authenticated
using (auth.uid()::text = user_id);

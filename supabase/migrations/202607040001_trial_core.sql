-- Durable trial grant, signed ledger, and remediation lifecycle schema.

alter table public.uploaded_files
    add column page_count integer null,
    add constraint ck_uploaded_files_page_count_nonnegative
        check (page_count is null or page_count >= 0);

create table public.trial_accounts (
    user_id text primary key references public.users(id) on delete cascade,
    normalized_email text not null,
    normalized_domain text not null,
    granted_pages integer not null,
    eligibility_rule_version text not null,
    created_at timestamp without time zone not null default (now() at time zone 'utc'),
    constraint ck_trial_accounts_granted_pages_nonnegative
        check (granted_pages >= 0),
    constraint ck_trial_accounts_normalized_email
        check (normalized_email = lower(trim(normalized_email))),
    constraint ck_trial_accounts_normalized_domain
        check (normalized_domain = lower(trim(normalized_domain)))
);

create table public.remediation_jobs (
    id text primary key,
    user_id text not null references public.users(id) on delete cascade,
    file_id text not null references public.uploaded_files(id) on delete cascade,
    report_id text null references public.accessibility_reports(id) on delete set null,
    status text not null,
    page_count integer not null,
    idempotency_key text not null,
    failure_reason text null,
    created_at timestamp without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp without time zone not null default (now() at time zone 'utc'),
    completed_at timestamp without time zone null,
    constraint uq_remediation_jobs_user_idempotency
        unique (user_id, idempotency_key),
    constraint ck_remediation_jobs_status
        check (status in ('pending', 'reserved', 'processing', 'succeeded', 'failed', 'released')),
    constraint ck_remediation_jobs_page_count_nonnegative
        check (page_count >= 0)
);

create index ix_remediation_jobs_file_id
    on public.remediation_jobs (file_id);
create index ix_remediation_jobs_report_id
    on public.remediation_jobs (report_id);
create index ix_remediation_jobs_status
    on public.remediation_jobs (status);

create table public.trial_ledger_entries (
    id text primary key,
    user_id text not null references public.users(id) on delete cascade,
    job_id text null references public.remediation_jobs(id) on delete set null,
    entry_type text not null,
    granted_delta integer not null default 0,
    reserved_delta integer not null default 0,
    consumed_delta integer not null default 0,
    idempotency_key text not null,
    created_at timestamp without time zone not null default (now() at time zone 'utc'),
    constraint uq_trial_ledger_user_idempotency
        unique (user_id, idempotency_key),
    constraint ck_trial_ledger_entry_type
        check (entry_type in ('grant', 'reserve', 'consume', 'release'))
);

create index ix_trial_ledger_entries_job_id
    on public.trial_ledger_entries (job_id);

create function public.prevent_trial_grant_provenance_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.granted_pages is distinct from old.granted_pages
       or new.eligibility_rule_version is distinct from old.eligibility_rule_version then
        raise exception 'trial account grant provenance is immutable';
    end if;
    return new;
end;
$$;

create trigger trial_accounts_immutable_grant_provenance
before update on public.trial_accounts
for each row execute function public.prevent_trial_grant_provenance_update();

create function public.set_remediation_job_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now() at time zone 'utc';
    return new;
end;
$$;

create trigger remediation_jobs_set_updated_at
before update on public.remediation_jobs
for each row execute function public.set_remediation_job_updated_at();

alter table public.trial_accounts enable row level security;
alter table public.trial_ledger_entries enable row level security;
alter table public.remediation_jobs enable row level security;

create policy "Users can view their own trial account"
on public.trial_accounts
for select
to authenticated
using (auth.uid()::text = user_id);

create policy "Users can view their own trial ledger entries"
on public.trial_ledger_entries
for select
to authenticated
using (auth.uid()::text = user_id);

create policy "Users can view their own remediation jobs"
on public.remediation_jobs
for select
to authenticated
using (auth.uid()::text = user_id);
